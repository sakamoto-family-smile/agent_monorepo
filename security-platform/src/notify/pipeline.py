"""通知のジョブ (notify サービス)。

| ジョブ | 間隔 | 内容 |
|---|---|---|
| notify_events | 5 分 | detection.db の events から P1 (新規・再発・P1 への引き上げ) を LINE ですぐ送る |
| notify_health | 30 分 | 取得停止など (health.py) の状態が変わったら LINE で送る (停止・復旧) |
| notify_digest | 15 分 | 1 日 1 回、DIGEST_HOUR 時を過ぎたら日次まとめを LINE で送る |
| notify_issues | 30 分 | 未対応の Finding を GitHub Issues (private リポジトリ) に写す |

notify.db にだけ書き、detection.db・intel.db は読み取り専用で開く。送った通知は
notifications.dedupe_key で記録し、途中で落ちても同じものを二重に送らない。
送り先が未設定なら送らずに ``skipped`` として記録する (イベントの処理は進める)。
"""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Engine, text

from ..common.events import Consumer, Event
from ..common.timeutil import parse_iso, to_iso, utc_now
from . import issues, messages
from .channels import GitHubIssues, LineChannel
from .health import Check, detection_checks, feed_checks, host_checks, intel_checks

logger = logging.getLogger(__name__)

JOB_EVENTS = "notify_events"
JOB_HEALTH = "notify_health"
JOB_DIGEST = "notify_digest"
JOB_ISSUES = "notify_issues"
FINDING_EVENTS = ("finding.opened", "finding.reopened", "finding.updated")


@dataclass(frozen=True)
class NotifySettings:
    timezone: ZoneInfo
    digest_hour: int
    issue_min_priority: str
    scan_interval: timedelta
    sbom_max_age: timedelta
    intel_schedule: dict[str, timedelta]
    host_max_age: timedelta = timedelta(hours=48)


def is_p1_alert(event: Event) -> bool:
    p = event.payload
    if p.get("priority") != "P1":
        return False
    return event.type != "finding.updated" or p.get("previous_priority") != "P1"


class NotifyPipeline:
    def __init__(
        self, engine: Engine, detection: Callable[[], Engine | None], intel: Callable[[], Engine | None],
        sbom_dir: Path, line: LineChannel, github: GitHubIssues, cfg: NotifySettings,
        hosts_dir: Path | None = None,
    ) -> None:
        self.engine = engine
        self._detection = detection  # 読み取り専用。まだ無ければ None (起動順に依存しない)
        self._intel = intel
        self.sbom_dir = sbom_dir
        self.hosts_dir = hosts_dir
        self.line = line
        self.github = github
        self.cfg = cfg

    # ── 実行記録 ──────────────────────────────────────────────────────────
    @contextmanager
    def _run(self, job: str) -> Iterator[dict[str, object]]:
        run_id = f"run_{uuid.uuid4().hex[:16]}"
        detail: dict[str, object] = {}
        with self.engine.begin() as conn:
            conn.execute(text("INSERT INTO job_runs (run_id, job, started_at, status) VALUES (:r, :j, :t, 'running')"),
                         {"r": run_id, "j": job, "t": to_iso(utc_now())})
        try:
            yield detail
        except Exception as e:
            self._finish(run_id, "failed", detail, f"{type(e).__name__}: {e}"[:2000])
            raise
        self._finish(run_id, "success", detail, None)

    def _finish(self, run_id: str, status: str, detail: dict[str, object], error: str | None) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE job_runs SET finished_at = :t, status = :s, detail = :d, error = :e "
                              "WHERE run_id = :r"),
                         {"t": to_iso(utc_now()), "s": status, "d": json.dumps(detail, ensure_ascii=False),
                          "e": error, "r": run_id})

    def last_success(self, job: str) -> datetime | None:
        with self.engine.connect() as conn:
            v = conn.execute(text("SELECT MAX(finished_at) FROM job_runs WHERE job = :j AND status = 'success'"),
                             {"j": job}).scalar()
        return parse_iso(v) if v else None

    # ── 送信 ──────────────────────────────────────────────────────────────
    def _already_sent(self, dedupe_key: str) -> bool:
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT 1 FROM notifications WHERE dedupe_key = :k"),
                                {"k": dedupe_key}).first() is not None

    def _send(self, kind: str, body: str, dedupe_key: str, conn: Connection | None = None) -> str:
        """LINE で送って記録する。送り先が未設定なら skipped。失敗は例外 (記録しないので次回また送る)。"""
        status = "skipped"
        if self.line.configured:
            self.line.send(body, dedupe_key)
            status = "sent"
        else:
            logger.info("LINE が未設定のため送りません (%s):\n%s", kind, body)
        stmt = text("INSERT OR IGNORE INTO notifications (dedupe_key, channel, kind, status, body, sent_at) "
                    "VALUES (:k, 'line', :kind, :s, :b, :t)")
        params = {"k": dedupe_key, "kind": kind, "s": status, "b": body, "t": to_iso(utc_now())}
        if conn is not None:
            conn.execute(stmt, params)
        else:
            with self.engine.begin() as c:
                c.execute(stmt, params)
        return status

    # ── P1 の即時通知 ──────────────────────────────────────────────────────
    def run_events(self) -> None:
        with self._run(JOB_EVENTS) as detail:
            detection = self._detection()
            if detection is None:
                detail["skipped"] = "detection.db がありません"
                return
            consumer = Consumer(detection, self.engine, "detection")
            if self._needs_baseline(consumer):
                # 初回 (と detection.db を作り直したとき) は今までのイベントを通知しない
                # (導入時や作り直しで、過去の P1 をまとめて送らない)
                with detection.connect() as conn:
                    head = conn.execute(text("SELECT COALESCE(MAX(seq), 0) FROM events")).scalar_one()
                consumer.ack(head)
                detail["baseline"] = head
                return
            sent = 0
            while batch := consumer.fetch(FINDING_EVENTS):
                alerts = [e for e in batch if is_p1_alert(e)]
                ids = [e.payload["finding_id"] for e in alerts]
                rows = {f.finding_id: f for f in messages.load_findings(
                    detection, "finding_id IN (" + ", ".join(f":f{i}" for i in range(len(ids))) + ") AND state = 'open'",
                    {f"f{i}": v for i, v in enumerate(ids)},
                )} if ids else {}
                findings = [rows[i] for i in dict.fromkeys(ids) if i in rows]
                key = f"p1:{batch[-1].event_id}"
                with self.engine.begin() as conn:
                    if findings and not self._already_sent(key):
                        self._send("finding", messages.p1_alert(findings, self.cfg.timezone), key, conn)
                        sent += len(findings)
                    consumer.ack(batch[-1].seq, conn)
            detail["p1"] = sent

    def _needs_baseline(self, consumer: Consumer) -> bool:
        with self.engine.connect() as conn:
            epoch = conn.execute(text("SELECT epoch FROM event_cursors WHERE source = 'detection'")).scalar()
        return epoch is None or epoch != consumer.source_epoch()

    # ── 取得停止の監視 ────────────────────────────────────────────────────
    def checks(self, now: datetime) -> list[Check]:
        hosts = host_checks(self.hosts_dir, self.cfg.host_max_age, now) if self.hosts_dir else []
        intel = self._intel()
        return intel_checks(intel, self.cfg.intel_schedule, now) + feed_checks(intel, now) + detection_checks(
            self._detection(), self.cfg.scan_interval, self.sbom_dir, self.cfg.sbom_max_age, now) + hosts

    def run_health(self) -> None:
        with self._run(JOB_HEALTH) as detail:
            now = utc_now()
            checks = self.checks(now)
            with self.engine.connect() as conn:
                prev = {r[0]: bool(r[1]) for r in conn.execute(text("SELECT key, ok FROM alert_states")).all()}
            # 初めて見る項目は、止まっているときだけ知らせる
            changed = [(c, prev.get(c.key, True)) for c in checks if prev.get(c.key, True) != c.ok]
            with self.engine.begin() as conn:
                if changed:
                    key = "health:" + ";".join(f"{c.key}={'ok' if c.ok else 'stale'}" for c, _ in changed) \
                          + f"@{to_iso(now)}"
                    self._send("health", messages.health_alert(changed), key, conn)
                for c in checks:
                    conn.execute(text("""
                        INSERT INTO alert_states (key, ok, since, detail, updated_at) VALUES (:k, :ok, :t, :d, :t)
                        ON CONFLICT(key) DO UPDATE SET detail = excluded.detail, updated_at = excluded.updated_at,
                          since = CASE WHEN alert_states.ok = excluded.ok THEN alert_states.since ELSE excluded.since END,
                          ok = excluded.ok
                    """), {"k": c.key, "ok": c.ok, "t": to_iso(now), "d": c.detail})
            detail.update(checks=len(checks), stale=sum(not c.ok for c in checks), changed=len(changed))

    # ── 日次まとめ ────────────────────────────────────────────────────────
    def run_digest(self, now: datetime | None = None, *, force: bool = False) -> None:
        """force なら時刻を待たずに送る (その日にまだ送っていなければ)。"""
        with self._run(JOB_DIGEST) as detail:
            now = now or utc_now()
            local = now.astimezone(self.cfg.timezone)
            key = f"digest:{local:%Y-%m-%d}"
            if (local.hour < self.cfg.digest_hour and not force) or self._already_sent(key):
                detail["skipped"] = "not due"
                return
            detection = self._detection()
            if detection is None:
                detail["skipped"] = "detection.db がありません"
                return
            with self.engine.connect() as conn:
                last = conn.execute(text("SELECT MAX(sent_at) FROM notifications WHERE kind = 'digest'")).scalar()
            since = parse_iso(last) if last else now - timedelta(days=1)
            body = messages.digest(detection, since, now, self.checks(now), self.cfg.timezone)
            detail["status"] = self._send("digest", body, key)

    # ── GitHub Issues ─────────────────────────────────────────────────────
    def run_issues(self) -> None:
        with self._run(JOB_ISSUES) as detail:
            detection = self._detection()
            if not self.github.configured or detection is None:
                detail["skipped"] = "GitHub Issues が未設定" if detection else "detection.db がありません"
                return
            r = issues.sync(detection, self.engine, self.github, self.cfg.issue_min_priority, self.cfg.timezone,
                            utc_now())
            detail.update(vars(r))

    def send_test(self) -> str:
        return self._send("test", "security-platform の通知テストです。", f"test:{uuid.uuid4().hex}")
