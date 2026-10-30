"""未対応の Finding を GitHub Issues (private リポジトリ) に写す。

パッケージ (エコシステム + 名前) ごとに 1 Issue。同じパッケージを複数のサービスが使っていても
直すのは 1 回 (同じ版に上げる) なので、まとめて 1 つにする。
イベントではなく detection.db の今の状態から毎回組み立て直し、notify.db の issues と比べて
変わったものだけ作成・更新・クローズする (取りこぼしても次の同期で揃う)。
公開リポジトリには立てない (未対応の脆弱性の一覧になるため)。
"""
from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, text

from ..common.timeutil import to_iso
from ..detection.triage import PRIORITIES
from .channels import GitHubIssues
from .messages import FindingRow, load_findings, sorted_versions, source_label

logger = logging.getLogger(__name__)

LABEL_COLORS = {"security": "b60205", "P1": "b60205", "P2": "d93f0b", "P3": "fbca04"}
MAX_CHANGES_PER_RUN = 40  # GitHub の二次レート制限 (作成は 1 分 80 件程度) に余裕を持たせる
PAUSE_SECONDS = 1.0


@dataclass(frozen=True)
class IssueDraft:
    group_key: str
    title: str
    body: str
    labels: list[str]

    @property
    def body_hash(self) -> str:
        return hashlib.sha256(f"{self.title}\n{self.labels}\n{self.body}".encode()).hexdigest()


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    closed: int = 0
    reopened: int = 0
    deferred: int = 0  # 上限に達して次回に回した件数


def _render(key: str, fs: list[FindingRow], tz: ZoneInfo) -> IssueDraft:
    eco, name = key.split("/", 1)
    priority = min(f.priority for f in fs)
    fixes = sorted_versions(eco, {f.fixed_version for f in fs if f.fixed_version})
    due = min((f.due_at for f in fs if f.due_at), default=None)
    services = sorted({f.service_id for f in fs})
    title = f"[{priority}] {name} ({eco}) の脆弱性"
    lines = [
        f"<!-- security-platform:group={key} -->",
        f"**{name}** ({eco}) に未対応の脆弱性があります。security-platform の照合結果から自動で更新します。",
        "",
        f"- 優先度: **{priority}**" + (f" / 期限 {due.astimezone(tz):%Y-%m-%d}" if due else ""),
        f"- 修正版: {', '.join(fixes) if fixes else 'なし (上流・ディストリビューションの修正待ち)'}"
        + (f" (**{fixes[-1]} 以上**に上げるとすべて解消)" if len(fixes) > 1 else ""),
        f"- 対象サービス: {', '.join(services)}",
        "",
        "| 優先度 | サービス | バージョン | Advisory | 修正版 | 理由 | 見つかった元 |",
        "|---|---|---|---|---|---|---|",
    ]
    for f in sorted(fs, key=lambda f: (f.priority, f.service_id, f.advisory_id)):
        lines.append(f"| {f.priority} | {f.service_id} | {f.version} | {f.advisory_id} | {f.fixed_version or '-'} "
                     f"| {'・'.join(f.reasons)} | {source_label(f.source_kind)} |")
    lines += ["", "解消 (更新・例外の登録) すると次の同期で自動的にクローズします。"]
    return IssueDraft(key, title, "\n".join(lines), ["security", priority])


def drafts(detection: Engine, min_priority: str, tz: ZoneInfo) -> dict[str, IssueDraft]:
    targets = PRIORITIES[: PRIORITIES.index(min_priority) + 1]
    marks = ", ".join(f"'{p}'" for p in targets)  # PRIORITIES の固定値だけ
    groups: dict[str, list[FindingRow]] = defaultdict(list)
    for f in load_findings(detection, f"state = 'open' AND priority IN ({marks})"):  # nosec B608
        groups[f"{f.ecosystem}/{f.package}"].append(f)
    return {k: _render(k, fs, tz) for k, fs in groups.items()}


def sync(
    detection: Engine, own: Engine, gh: GitHubIssues, min_priority: str, tz: ZoneInfo, now: datetime,
    sleep: Callable[[float], None] = time.sleep,
) -> SyncResult:
    result = SyncResult()
    wanted = drafts(detection, min_priority, tz)
    with own.connect() as conn:
        known = {r[0]: (r[1], r[2], r[3]) for r in conn.execute(
            text("SELECT group_key, number, state, body_hash FROM issues")).all()}
    for name, color in LABEL_COLORS.items():
        gh.ensure_label(name, color)
    budget = MAX_CHANGES_PER_RUN

    def save(key: str, number: int, state: str, title: str, body_hash: str) -> None:
        with own.begin() as conn:
            conn.execute(text("""
                INSERT INTO issues (group_key, number, state, title, body_hash, updated_at)
                VALUES (:k, :n, :s, :t, :h, :u)
                ON CONFLICT(group_key) DO UPDATE SET number = excluded.number, state = excluded.state,
                  title = excluded.title, body_hash = excluded.body_hash, updated_at = excluded.updated_at
            """), {"k": key, "n": number, "s": state, "t": title, "h": body_hash, "u": to_iso(now)})

    for key, d in sorted(wanted.items(), key=lambda kv: kv[1].title):
        prev = known.get(key)
        if prev is not None and prev[1] == "open" and prev[2] == d.body_hash:
            continue
        if budget <= 0:
            result.deferred += 1
            continue
        budget -= 1
        if prev is None:
            number = gh.create(d.title, d.body, d.labels)
            result.created += 1
        else:
            number = prev[0]
            gh.update(number, title=d.title, body=d.body, labels=d.labels, state="open")
            if prev[1] == "closed":
                result.reopened += 1
            else:
                result.updated += 1
        save(key, number, "open", d.title, d.body_hash)
        sleep(PAUSE_SECONDS)
    for key, (number, state, _) in sorted(known.items()):
        if state != "open" or key in wanted:
            continue
        if budget <= 0:
            result.deferred += 1
            continue
        budget -= 1
        eco, name = key.split("/", 1)
        title = f"[解消] {name} ({eco}) の脆弱性"
        body = f"<!-- security-platform:group={key} -->\n未対応の Finding がなくなりました (更新・例外の登録)。"
        gh.update(number, title=title, body=body, labels=["security"], state="closed")
        save(key, number, "closed", title, "")
        result.closed += 1
        sleep(PAUSE_SECONDS)
    if result.deferred:
        logger.info("issues: %d 件を次回に回します (1 回の上限 %d)", result.deferred, MAX_CHANGES_PER_RUN)
    return result
