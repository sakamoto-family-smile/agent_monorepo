"""A2 の照合ジョブ: services.yaml → lockfile・本番イメージの SBOM → 照合 → 優先度 → findings。

1 回の照合で全サービスを最初から照合し、結果を findings と突き合わせる。
- 新しく該当したもの → open (以前 resolved なら reopened)
- 優先度・修正版などが変わったもの → updated
- 該当しなくなったもの (更新済み・Advisory の取り下げ等) → resolved
変化は detection.db の events (finding.*) に、状態遷移は finding_transitions に残す。
intel.db は読み取り専用で開き、契約のビューだけを読む。
本番イメージの SBOM は ``make detection-images`` (images.py) が data/sbom/images/ に置いたものを読む。
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, text

from ..common.events import Outbox
from ..common.paths import DataPaths
from ..common.services import Service
from ..common.timeutil import parse_iso, to_iso, utc_now, utc_now_iso
from .image_sbom import InvalidSbom, parse_image_sbom
from .images import blob_path, is_digest, read_manifest, repository_of
from .lockfiles import Component, ParsedLockfile, UnsupportedLockfile, parse_lockfile
from .matcher import Match, Matcher
from .triage import PRIORITIES, Triage, due_at, triage

logger = logging.getLogger(__name__)

JOB_SCAN = "scan"
STATE_OPEN = "open"
STATE_RESOLVED = "resolved"
EVENT_OPENED = "finding.opened"
EVENT_REOPENED = "finding.reopened"
EVENT_UPDATED = "finding.updated"
EVENT_RESOLVED = "finding.resolved"


@dataclass
class ScanResult:
    run_id: str
    services: int = 0
    components: int = 0
    open_findings: int = 0
    opened: int = 0
    updated: int = 0
    resolved: int = 0
    warnings: list[str] = field(default_factory=list)
    # lockfile・イメージの SBOM を読めなかったサービス。照合結果が欠けているので、その Finding は閉じない
    incomplete: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class Desired:
    """今回の照合で該当した 1 件 (service × advisory × purl)。"""

    service: Service
    match: Match
    triage: Triage
    source: ParsedLockfile  # 見つかった元 (lockfile か本番イメージ)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.service.id, self.match.advisory.advisory_id, self.match.component.purl)

    @property
    def finding_id(self) -> str:
        return "fnd_" + hashlib.sha256("\n".join(self.key).encode()).hexdigest()[:20]

    def evidence(self) -> dict[str, Any]:
        adv, comp = self.match.advisory, self.match.component
        return {
            "summary": adv.summary, "kind": adv.kind, "severity": adv.severity,
            "cvss_score": adv.cvss_score, "kev": adv.kev, "epss": adv.epss, "cves": list(adv.cves),
            "record_ids": list(self.match.record_ids), "ecosystem": comp.ecosystem,
            "package": comp.name, "version": comp.version, "scope": comp.scope,
            "source": self.source.path, "source_kind": self.source.kind, "reasons": list(self.triage.reasons),
        }


class DetectionPipeline:
    def __init__(
        self, engine: Engine, intel_engine: Engine, paths: DataPaths, repo_root: Path,
        services: list[Service], image_sbom_max_age: timedelta = timedelta(days=7),
    ) -> None:
        self.engine = engine
        self.paths = paths
        self.repo_root = repo_root
        self.services = services
        self.image_sbom_max_age = image_sbom_max_age
        self.matcher = Matcher(intel_engine)

    # ── 実行記録 ──────────────────────────────────────────────────────────
    @contextmanager
    def _run(self, job: str) -> Iterator[ScanResult]:
        result = ScanResult(f"run_{uuid.uuid4().hex[:16]}")
        with self.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO scan_runs (run_id, job, started_at, status) VALUES (:r, :j, :t, 'running')"),
                {"r": result.run_id, "j": job, "t": utc_now_iso()},
            )
        try:
            yield result
        except Exception as e:
            self._finish(result, "failed", f"{type(e).__name__}: {e}"[:2000])
            raise
        self._finish(result, "success", None)

    def _finish(self, r: ScanResult, status: str, error: str | None) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text("UPDATE scan_runs SET finished_at = :t, status = :s, services = :sv, "
                     "components = :c, open_findings = :o, opened = :op, updated = :u, resolved = :rs, "
                     "warnings_json = :w, error = :e WHERE run_id = :r"),
                {"t": utc_now_iso(), "s": status, "sv": r.services, "c": r.components,
                 "o": r.open_findings, "op": r.opened, "u": r.updated, "rs": r.resolved,
                 "w": json.dumps(r.warnings, ensure_ascii=False), "e": error, "r": r.run_id},
            )

    def last_success(self, job: str) -> datetime | None:
        with self.engine.connect() as conn:
            v = conn.execute(
                text("SELECT MAX(finished_at) FROM scan_runs WHERE job = :j AND status = 'success'"),
                {"j": job},
            ).scalar()
        return parse_iso(v) if v else None

    # ── 照合 ──────────────────────────────────────────────────────────────
    def run_scan(self) -> ScanResult:
        with self._run(JOB_SCAN) as result:
            now = utc_now()
            desired: dict[tuple[str, str, str], Desired] = {}
            with self.engine.begin() as conn:
                self._sync_services(conn, now)
                for svc in self.services:
                    parsed = self._parse_service(svc, result) + self._parse_images(svc, result, now)
                    self._save_sboms(conn, svc, parsed, now)
                    comps = _dedupe([(c, lf) for lf in parsed for c in lf.components])
                    result.services += 1
                    result.components += len(comps)
                    matches, _ = self.matcher.match([c for c, _ in comps])
                    where = {c.purl: lf for c, lf in comps}
                    for m in matches:
                        tri = triage(m.advisory, m.component, svc, m.fixed_version)
                        d = Desired(svc, m, tri, where[m.component.purl])
                        desired[d.key] = d
            outbox = Outbox(self.paths.events_dir, "detection")
            try:
                with self.engine.begin() as conn:
                    self._reconcile(conn, outbox, desired, now, result)
            except Exception:
                outbox.discard()
                raise
            outbox.flush()
            logger.info(
                "scan: %d services, %d components, %d open (+%d / ~%d / -%d)", result.services,
                result.components, result.open_findings, result.opened, result.updated, result.resolved,
            )
            return result

    def _parse_service(self, svc: Service, result: ScanResult) -> list[ParsedLockfile]:
        out = []
        for name in svc.lockfiles:
            rel = f"{svc.path}{name}"
            path = self.repo_root / rel
            try:
                out.append(parse_lockfile(path, rel))
            except FileNotFoundError:
                self._warn(result, svc, f"{rel} がありません")
            except (UnsupportedLockfile, ValueError) as e:
                self._warn(result, svc, f"{rel} を読めません ({e})")
        return out

    def _parse_images(self, svc: Service, result: ScanResult, now: datetime) -> list[ParsedLockfile]:
        """services.yaml の images と、make detection-images が作ったマニフェストを突き合わせて読む。"""
        if not svc.images:
            return []
        sbom_dir = self.paths.sbom_images_dir
        try:
            manifest = read_manifest(sbom_dir, svc.id)
        except ValueError as e:
            self._warn(result, svc, str(e))
            return []
        if manifest is None:
            self._warn(result, svc, "本番イメージの SBOM がありません (make detection-images)")
            return []
        entries = [e for e in manifest["images"] if isinstance(e, dict)]
        missing = sorted({r.key for r in svc.images} - {e.get("ref") for e in entries})
        if missing:
            self._warn(result, svc, f"SBOM の無いイメージがあります: {', '.join(missing)} (make detection-images)")
        try:
            generated = parse_iso(str(manifest["generated_at"]))
        except (KeyError, ValueError):
            generated = None
        if generated is None or now - generated > self.image_sbom_max_age:
            # 再デプロイ後に作り直していない恐れ。照合は続ける (古くても何もないよりよい)
            message = f"{svc.id}: 本番イメージの SBOM が古くなっています (make detection-images)"
            logger.warning(message)
            result.warnings.append(message)
        out: dict[str, ParsedLockfile] = {}
        for e in entries:
            digest = str(e.get("digest") or "")
            if digest in out:
                continue  # 同じイメージを使うサービス・ジョブはまとめて 1 回
            if not is_digest(digest):
                self._warn(result, svc, f"マニフェストのダイジェストが不正です ({e.get('ref')})")
                continue
            repository = repository_of(str(e.get("image") or ""))
            try:
                out[digest] = parse_image_sbom(blob_path(sbom_dir, digest), f"image:{repository}@{digest}", digest)
            except InvalidSbom as err:
                self._warn(result, svc, f"本番イメージの SBOM を読めません ({err})")
        return list(out.values())

    @staticmethod
    def _warn(result: ScanResult, svc: Service, message: str) -> None:
        logger.warning("%s: %s", svc.id, message)
        result.warnings.append(f"{svc.id}: {message}")
        result.incomplete.add(svc.id)

    def _sync_services(self, conn: Connection, now: datetime) -> None:
        for s in self.services:
            conn.execute(
                text("""
                    INSERT INTO services (service_id, path, exposure, deployed, auto_remediation,
                      config_json, updated_at)
                    VALUES (:id, :path, :exposure, :deployed, :auto, :cfg, :now)
                    ON CONFLICT(service_id) DO UPDATE SET path = excluded.path,
                      exposure = excluded.exposure, deployed = excluded.deployed,
                      auto_remediation = excluded.auto_remediation, config_json = excluded.config_json,
                      updated_at = excluded.updated_at
                """),
                {"id": s.id, "path": s.path, "exposure": s.exposure, "deployed": s.deployed,
                 "auto": s.auto_remediation, "cfg": s.model_dump_json(), "now": to_iso(now)},
            )

    def _save_sboms(self, conn: Connection, svc: Service, parsed: list[ParsedLockfile], now: datetime) -> None:
        """lockfile の内容 (sha256)・イメージのダイジェストごとに 1 つの SBOM。同じなら作り直さない。"""
        current = []
        for lf in parsed:
            sbom_id = f"sbom_{hashlib.sha256(f'{svc.id}\n{lf.path}\n{lf.sha256}'.encode()).hexdigest()[:20]}"
            current.append(sbom_id)
            exists = conn.execute(text("SELECT 1 FROM sboms WHERE sbom_id = :i"), {"i": sbom_id}).first()
            if exists:
                continue
            conn.execute(
                text("INSERT INTO sboms (sbom_id, service_id, kind, subject, path, is_current, generated_at) "
                     "VALUES (:i, :s, :k, :subj, :p, 0, :t)"),
                {"i": sbom_id, "s": svc.id, "k": lf.kind, "subj": lf.subject or f"sha256:{lf.sha256}",
                 "p": lf.path, "t": to_iso(now)},
            )
            rows = [{"i": sbom_id, "purl": c.purl, "e": c.ecosystem, "n": c.name, "v": c.version,
                     "d": c.is_direct} for c in lf.components]
            if rows:
                conn.execute(
                    text("INSERT OR IGNORE INTO sbom_components (sbom_id, purl, ecosystem, name, version, "
                         "is_direct) VALUES (:i, :purl, :e, :n, :v, :d)"),
                    rows,
                )
        conn.execute(text("UPDATE sboms SET is_current = 0 WHERE service_id = :s"), {"s": svc.id})
        for sbom_id in current:
            conn.execute(text("UPDATE sboms SET is_current = 1 WHERE sbom_id = :i"), {"i": sbom_id})

    # ── findings との突き合わせ ────────────────────────────────────────────
    def _reconcile(
        self, conn: Connection, outbox: Outbox, desired: dict[tuple[str, str, str], Desired],
        now: datetime, result: ScanResult,
    ) -> None:
        existing = {
            (r[1], r[2], r[3]): r
            for r in conn.execute(text(
                "SELECT finding_id, service_id, advisory_id, purl, state, priority, due_at, fixed_version, "
                "evidence_json, first_seen_at FROM findings"
            )).all()
        }
        for key, d in desired.items():
            row = existing.get(key)
            if row is None:
                self._open(conn, outbox, d, now)
                result.opened += 1
            elif row[4] == STATE_RESOLVED:
                self._reopen(conn, outbox, d, row, now)
                result.opened += 1
            elif self._update(conn, outbox, d, row, now):
                result.updated += 1
        for key, row in existing.items():
            # services.yaml から外したサービスの Finding も、照合しなくなったので閉じる
            if key not in desired and row[4] == STATE_OPEN and key[0] not in result.incomplete:
                self._resolve(conn, outbox, row, now)
                result.resolved += 1
        result.open_findings = conn.execute(
            text("SELECT count(*) FROM findings WHERE state = :s"), {"s": STATE_OPEN}
        ).scalar_one()

    def _payload(self, d: Desired, finding_id: str, due: datetime | None) -> dict[str, Any]:
        return {
            "finding_id": finding_id, "service_id": d.service.id,
            "advisory_id": d.match.advisory.advisory_id, "purl": d.match.component.purl,
            "priority": d.triage.priority, "due_at": to_iso(due) if due else None,
            "fixed_version": d.match.fixed_version, "summary": d.match.advisory.summary,
            "reasons": list(d.triage.reasons),
        }

    def _transition(self, conn: Connection, finding_id: str, frm: str | None, to: str, reason: str,
                    now: datetime) -> None:
        conn.execute(
            text("INSERT INTO finding_transitions (finding_id, from_state, to_state, reason, actor, occurred_at) "
                 "VALUES (:f, :fr, :to, :r, 'detection', :t)"),
            {"f": finding_id, "fr": frm, "to": to, "r": reason, "t": to_iso(now)},
        )

    def _write(self, conn: Connection, d: Desired, finding_id: str, due: datetime | None, now: datetime,
               *, insert: bool) -> None:
        params = {
            "id": finding_id, "s": d.service.id, "a": d.match.advisory.advisory_id,
            "p": d.match.component.purl, "dep": "direct" if d.match.component.is_direct else "transitive",
            "prio": d.triage.priority, "due": to_iso(due) if due else None,
            "fix_type": "upgrade" if d.match.fixed_version else "none", "fixed": d.match.fixed_version,
            "ev": json.dumps(d.evidence(), ensure_ascii=False, sort_keys=True), "now": to_iso(now),
        }
        if insert:
            conn.execute(text("""
                INSERT INTO findings (finding_id, service_id, advisory_id, purl, dependency_path, trigger,
                  priority, due_at, fix_type, fixed_version, state, evidence_json, first_seen_at, updated_at)
                VALUES (:id, :s, :a, :p, :dep, 'scan', :prio, :due, :fix_type, :fixed, 'open', :ev, :now, :now)
            """), params)
        else:
            conn.execute(text("""
                UPDATE findings SET dependency_path = :dep, priority = :prio, due_at = :due,
                  fix_type = :fix_type, fixed_version = :fixed, state = 'open', evidence_json = :ev,
                  updated_at = :now, closed_at = NULL
                WHERE finding_id = :id
            """), params)

    def _open(self, conn: Connection, outbox: Outbox, d: Desired, now: datetime) -> None:
        due = due_at(d.triage.priority, now)
        self._write(conn, d, d.finding_id, due, now, insert=True)
        self._transition(conn, d.finding_id, None, STATE_OPEN, "detected", now)
        outbox.publish(conn, EVENT_OPENED, self._payload(d, d.finding_id, due))

    def _reopen(self, conn: Connection, outbox: Outbox, d: Desired, row: Any, now: datetime) -> None:
        due = due_at(d.triage.priority, now)
        self._write(conn, d, row[0], due, now, insert=False)
        self._transition(conn, row[0], STATE_RESOLVED, STATE_OPEN, "detected again", now)
        outbox.publish(conn, EVENT_REOPENED, self._payload(d, row[0], due))

    def _update(self, conn: Connection, outbox: Outbox, d: Desired, row: Any, now: datetime) -> bool:
        prev_priority, prev_due, prev_fixed, prev_ev = row[5], row[6], row[7], row[8]
        evidence = json.dumps(d.evidence(), ensure_ascii=False, sort_keys=True)
        if (prev_priority, prev_fixed, prev_ev) == (d.triage.priority, d.match.fixed_version, evidence):
            return False
        due = parse_iso(prev_due) if prev_due else None
        if PRIORITIES.index(d.triage.priority) < PRIORITIES.index(prev_priority):
            # 上がった (KEV 掲載など): 今から数えた期限が今の期限より早ければ早める
            raised = due_at(d.triage.priority, now)
            due = raised if due is None or (raised is not None and raised < due) else due
        elif d.triage.priority != prev_priority:
            due = due_at(d.triage.priority, parse_iso(row[9]))  # 下がった: 初回検知からの期限
        self._write(conn, d, row[0], due, now, insert=False)
        if d.triage.priority != prev_priority or d.match.fixed_version != prev_fixed:
            outbox.publish(conn, EVENT_UPDATED, {
                **self._payload(d, row[0], due), "previous_priority": prev_priority,
                "previous_fixed_version": prev_fixed,
            })
        return True

    def _resolve(self, conn: Connection, outbox: Outbox, row: Any, now: datetime) -> None:
        conn.execute(
            text("UPDATE findings SET state = :s, closed_at = :t, updated_at = :t WHERE finding_id = :id"),
            {"s": STATE_RESOLVED, "t": to_iso(now), "id": row[0]},
        )
        self._transition(conn, row[0], STATE_OPEN, STATE_RESOLVED, "no longer matched", now)
        outbox.publish(conn, EVENT_RESOLVED, {
            "finding_id": row[0], "service_id": row[1], "advisory_id": row[2], "purl": row[3],
            "priority": row[5],
        })

    # ── 読み取り ──────────────────────────────────────────────────────────
    def open_findings(self) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT priority, due_at, service_id, advisory_id, purl, fixed_version, dependency_path, "
                "evidence_json FROM findings WHERE state = 'open' ORDER BY priority, due_at, service_id"
            )).all()
        return [
            {"priority": r[0], "due_at": r[1], "service_id": r[2], "advisory_id": r[3], "purl": r[4],
             "fixed_version": r[5], "dependency_path": r[6], **json.loads(r[7])}
            for r in rows
        ]


def _dedupe(items: list[tuple[Component, ParsedLockfile]]) -> list[tuple[Component, ParsedLockfile]]:
    """同じ purl が複数の lockfile・イメージにあれば 1 つにまとめる。

    元は runtime・direct のものを優先する。scope と is_direct はどれか 1 つでも当てはまれば立てる
    (lockfile では dev 依存でも、本番イメージに入っていれば runtime)。
    """
    def rank(c: Component) -> tuple[bool, bool]:
        return (c.scope != "runtime", not c.is_direct)

    best: dict[str, tuple[Component, ParsedLockfile]] = {}
    for c, lf in items:
        prev = best.get(c.purl)
        if prev is None:
            best[c.purl] = (c, lf)
            continue
        top, src = (c, lf) if rank(c) < rank(prev[0]) else prev
        best[c.purl] = (replace(
            top, is_direct=c.is_direct or prev[0].is_direct,
            scope="runtime" if "runtime" in (c.scope, prev[0].scope) else "dev",
        ), src)
    return list(best.values())
