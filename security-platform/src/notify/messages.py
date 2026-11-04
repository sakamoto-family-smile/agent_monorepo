"""通知文の組み立て (LINE のテキスト)。

detection.db は読み取り専用で開き、findings・exceptions・early_warnings を読むだけ。
日次まとめの「記事からの情報」は intel.db の report_claims を読み取り専用で読む。
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError

from ..common.timeutil import parse_iso, to_iso
from ..detection.versions import version_key
from .health import Check

DIGEST_LIST_LIMIT = 10


@dataclass(frozen=True)
class FindingRow:
    finding_id: str
    service_id: str
    advisory_id: str
    priority: str
    state: str
    due_at: datetime | None
    fixed_version: str | None
    first_seen_at: datetime
    package: str
    version: str
    ecosystem: str
    summary: str | None
    reasons: tuple[str, ...]
    source_kind: str


def load_findings(engine: Engine, where: str, params: dict[str, Any] | None = None) -> list[FindingRow]:
    """where はこのパッケージ内の固定の条件だけ。値は必ず params で渡す。"""
    sql = ("SELECT finding_id, service_id, advisory_id, priority, state, due_at, fixed_version, first_seen_at, "
           f"evidence_json FROM findings WHERE {where} "  # nosec B608  where は固定の条件、値は params
           "ORDER BY priority, due_at, service_id, advisory_id")
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params or {}).all()
    out = []
    for r in rows:
        ev = json.loads(r[8])
        out.append(FindingRow(
            r[0], r[1], r[2], r[3], r[4], parse_iso(r[5]) if r[5] else None, r[6], parse_iso(r[7]),
            str(ev.get("package") or "?"), str(ev.get("version") or "?"), str(ev.get("ecosystem") or "?"),
            ev.get("summary"), tuple(ev.get("reasons") or ()), str(ev.get("source_kind") or "source"),
        ))
    return out


SOURCE_LABELS = {"source": "lockfile", "image": "本番イメージ", "host": "開発 PC",
                 "host_history": "開発 PC (過去に入っていた版)"}


def source_label(kind: str) -> str:
    return SOURCE_LABELS.get(kind, kind)


def _date(dt: datetime | None, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime("%m/%d") if dt else "-"


def _fix(f: FindingRow) -> str:
    return f"→ {f.fixed_version}" if f.fixed_version else "(修正版なし)"


def finding_line(f: FindingRow, tz: ZoneInfo) -> str:
    return (f"・{f.service_id}: {f.package} {f.version} {_fix(f)}\n"
            f"  {f.advisory_id} {'・'.join(f.reasons)} / 期限 {_date(f.due_at, tz)}")


def p1_alert(findings: list[FindingRow], tz: ZoneInfo) -> str:
    lines = [f"【至急】P1 の脆弱性 {len(findings)} 件 (悪用確認済み・悪性パッケージ)"]
    lines += [finding_line(f, tz) for f in findings]
    lines.append("make detection-findings で一覧を確認できます")
    return "\n".join(lines)


KIND_LABELS = {"malicious": "悪性", "compromised": "侵害", "vulnerable": "脆弱性"}
STATUS_LABELS = {"confirmed": "確認済み", "unconfirmed": "未確認", "superseded": "OSV 登録済み"}


def _claim_versions(ev: dict[str, Any]) -> str:
    versions = ev.get("claim_versions") or []
    if not versions:
        return "記事に版の記載なし"
    shown = ", ".join(versions[:5]) + (" ほか" if len(versions) > 5 else "")
    return f"記事の版 {shown}" + (" と一致" if ev.get("version_matched") else " (使っている版とは違う)")


def warning_line(ev: dict[str, Any]) -> str:
    return (f"・{ev.get('service_id')}: {ev.get('ecosystem')} {ev.get('package')} {ev.get('version')} "
            f"({source_label(str(ev.get('source_kind') or 'source'))})\n"
            f"  {KIND_LABELS.get(str(ev.get('kind')), ev.get('kind'))}・"
            f"{STATUS_LABELS.get(str(ev.get('status')), ev.get('status'))} / {_claim_versions(ev)}\n"
            f"  {ev.get('feed_id')}: {str(ev.get('title') or '')[:120]}"
            + (f"\n  {ev['url']}" if ev.get("url") else ""))


def early_warning(evidence: list[dict[str, Any]]) -> str:
    """evidence: warning.opened の payload (service_id と early_warning.EarlyWarning.evidence)。"""
    lines = [f"【未確認情報】使っているパッケージと同じ名前の注意喚起 {len(evidence)} 件"]
    lines += [warning_line(ev) for ev in evidence]
    lines.append("一次情報で確認が取れていない記事です (Finding・Issue にはしていません)。記事と公式の告知を確かめてください")
    return "\n".join(lines)


def load_warnings(engine: Engine, ids: list[str] | None = None) -> list[dict[str, Any]]:
    """未対応の早期警告。detection.db が L4 より前なら空。"""
    sql = "SELECT warning_id, service_id, purl, evidence_json FROM early_warnings WHERE state = 'open'"
    params: dict[str, Any] = {}
    if ids is not None:
        if not ids:
            return []
        sql += " AND warning_id IN (" + ", ".join(f":w{i}" for i in range(len(ids))) + ")"
        params = {f"w{i}": v for i, v in enumerate(ids)}
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(sql + " ORDER BY first_seen_at, warning_id"), params).all()
    except OperationalError:
        return []
    return [{"warning_id": r[0], "service_id": r[1], "purl": r[2], **json.loads(r[3])} for r in rows]


def _claims_section(intel: Engine | None, since: datetime) -> list[str]:
    if intel is None:
        return []
    try:
        with intel.connect() as conn:
            rows = conn.execute(text("""
                SELECT c.status, c.ecosystem, c.package, c.kind, r.feed_id, r.title
                FROM report_claims c JOIN reports r ON r.report_id = c.report_id
                WHERE c.grounded = 1 AND c.extracted_at > :s ORDER BY c.status, r.first_seen_at, c.claim_id
            """), {"s": to_iso(since)}).all()
    except OperationalError:
        return []
    if not rows:
        return []
    n = {k: sum(1 for r in rows if r[0] == k) for k in STATUS_LABELS}
    lines = ["■ 記事からの情報 (前回から): " + " / ".join(f"{STATUS_LABELS[k]} {n[k]}" for k in STATUS_LABELS)]
    listed = [r for r in rows if r[0] in ("confirmed", "unconfirmed")]
    lines += [f"・{STATUS_LABELS[r[0]]} {r[1]} {r[2]} ({KIND_LABELS.get(r[3], r[3])}) — {r[4]}: {r[5][:80]}"
              for r in listed[:DIGEST_LIST_LIMIT]]
    if len(listed) > DIGEST_LIST_LIMIT:
        lines.append(f"  ほか {len(listed) - DIGEST_LIST_LIMIT} 件")
    return lines


def health_alert(changed: list[tuple[Check, bool]]) -> str:
    """changed: (今の状態, 前回は正常だったか)。"""
    lines = ["【監視】脆弱性情報の取り込み・照合の状態が変わりました"]
    for check, _ in changed:
        lines.append(f"・{'復旧' if check.ok else '停止'} {check.key}: {check.detail}")
    return "\n".join(lines)


def sorted_versions(ecosystem: str, versions: set[str]) -> list[str]:
    """エコシステムの比較規則で並べる (解釈できないものは文字列順で後ろに)。"""
    def key(v: str) -> tuple[int, object, str]:
        try:
            return (0, version_key(ecosystem, v), v)
        except ValueError:
            return (1, 0, v)
    try:
        return sorted(versions, key=key)
    except TypeError:  # 比較できない組み合わせ (MIN と文字列など)
        return sorted(versions)


def needed_fix(fs: list[FindingRow]) -> str | None:
    """すべての Advisory を直すのに要る版 (各 Finding の修正版のうち最大)。"""
    fixes = {f.fixed_version for f in fs if f.fixed_version}
    return sorted_versions(fs[0].ecosystem, fixes)[-1] if fixes else None


def _group(findings: list[FindingRow]) -> list[tuple[str, list[FindingRow]]]:
    groups: dict[str, list[FindingRow]] = defaultdict(list)
    for f in findings:
        groups[f"{f.package} {f.version}"].append(f)
    return sorted(groups.items(), key=lambda kv: (min(f.priority for f in kv[1]), kv[0]))


def _group_line(name: str, fs: list[FindingRow]) -> str:
    services = sorted({f.service_id for f in fs})
    fix = needed_fix(fs)
    return f"・{min(f.priority for f in fs)} {name} {f'→ {fix}' if fix else '(修正版なし)'} — " \
           f"脆弱性 {len({f.advisory_id for f in fs})} 件 / " \
           f"{', '.join(services[:3])}{f' ほか {len(services) - 3}' if len(services) > 3 else ''}"


def digest(
    engine: Engine, since: datetime, now: datetime, checks: list[Check], tz: ZoneInfo,
    intel: Engine | None = None,
) -> str:
    open_rows = load_findings(engine, "state = 'open'")
    counts = {p: sum(1 for f in open_rows if f.priority == p) for p in ("P1", "P2", "P3", "P4")}
    new = [f for f in open_rows if f.first_seen_at > since and f.priority != "P4"]
    overdue = [f for f in open_rows if f.due_at is not None and f.due_at < now]
    with engine.connect() as conn:
        resolved = conn.execute(text("SELECT count(*) FROM findings WHERE state = 'resolved' AND closed_at > :s"),
                                {"s": to_iso(since)}).scalar_one()
        suppressed = conn.execute(text("SELECT count(*) FROM findings WHERE state = 'suppressed'")).scalar_one()
        expiring = conn.execute(text(
            "SELECT advisory_id, service_id, expires_at FROM exceptions WHERE revoked_at IS NULL "
            "AND expires_at IS NOT NULL AND expires_at > :now AND expires_at <= :soon ORDER BY expires_at"
        ), {"now": to_iso(now), "soon": to_iso(now + timedelta(days=7))}).all()

    lines = [f"【脆弱性 日次まとめ】{now.astimezone(tz):%Y-%m-%d}",
             f"未対応: P1 {counts['P1']} / P2 {counts['P2']} / P3 {counts['P3']} / P4 {counts['P4']}"
             f" (例外で抑止 {suppressed})",
             f"前回から: 新規 {len(new)} 件 (P4 を除く) / 解消 {resolved} 件 / 期限切れ {len(overdue)} 件"]
    for title, rows in (("■ 新規", new), ("■ 期限切れ", overdue)):
        if not rows:
            continue
        lines.append(title)
        groups = _group(rows)
        lines += [_group_line(name, fs) for name, fs in groups[:DIGEST_LIST_LIMIT]]
        if len(groups) > DIGEST_LIST_LIMIT:
            lines.append(f"  ほか {len(groups) - DIGEST_LIST_LIMIT} パッケージ")
    warnings = load_warnings(engine)
    if warnings:
        lines.append(f"■ 未確認情報 (使っているパッケージと同じ名前) {len(warnings)} 件")
        lines += [f"・{w['service_id']}: {w.get('ecosystem')} {w.get('package')} {w.get('version')} "
                  f"({KIND_LABELS.get(str(w.get('kind')), w.get('kind'))}) — {w.get('feed_id')}"
                  for w in warnings[:DIGEST_LIST_LIMIT]]
        if len(warnings) > DIGEST_LIST_LIMIT:
            lines.append(f"  ほか {len(warnings) - DIGEST_LIST_LIMIT} 件")
    lines += _claims_section(intel, since)
    if expiring:
        lines.append("■ 7 日以内に切れる例外")
        lines += [f"・{a} ({s}) {_date(parse_iso(e), tz)}" for a, s, e in expiring]
    stale = [c for c in checks if not c.ok]
    if stale:
        lines.append("■ 止まっているもの")
        lines += [f"・{c.key}: {c.detail}" for c in stale]
    return "\n".join(lines)
