"""Advisory の変化検知 (FR-I05)、履歴、advisory.changed の発行 (FR-I06)。

1 回の実行で同じ Advisory に複数の変化があっても、イベントは 1 件にまとめる。
ブートストラップ中はイベントも履歴も書かない。取り込み結果を変化検知の基準値とする (FR-I10)。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from ..common.events import Outbox
from ..common.timeutil import utc_now_iso
from .rollup import (
    AdvisoryState,
    compute_state,
    delete_state,
    load_state,
    mark_upstream_dependents,
    save_state,
)

EVENT_ADVISORY_CHANGED = "advisory.changed"
EVENT_BOOTSTRAP_COMPLETED = "advisory.bootstrap_completed"
# これらの変化があったら、深刻度を引き継いでいる下流の Advisory も再集計する
SEVERITY_DEPENDENT_CHANGES = frozenset({"created", "removed", "severity_changed"})


@dataclass
class RunContext:
    run_id: str
    outbox: Outbox
    emit_events: bool = True
    fetched: int = 0
    skipped: int = 0
    changed: int = 0
    events: int = 0
    _signals: dict[str, set[str]] = field(default_factory=dict)

    def add_signal(self, advisory_id: str, change_type: str) -> None:
        """KEV・EPSS 由来の変化 (advisories 行には現れない) を積んでおく。"""
        self._signals.setdefault(advisory_id, set()).add(change_type)

    def pop_signals(self, advisory_id: str) -> set[str]:
        return self._signals.pop(advisory_id, set())

    def pending_signal_ids(self) -> list[str]:
        return sorted(self._signals)


def detect_changes(prev: dict[str, object] | None, cur: AdvisoryState | None) -> list[str]:
    if prev is None and cur is None:
        return []
    if prev is None:
        return ["created"]
    if cur is None:
        return ["removed"]
    types = []
    if not prev["withdrawn"] and cur.withdrawn:
        types.append("withdrawn")
    if prev["withdrawn"] and not cur.withdrawn:
        types.append("reinstated")
    if prev["fixed_hash"] != cur.fixed_hash:
        types.append("fixed_version_published")
    if prev["affected_hash"] != cur.affected_hash:
        types.append("affected_changed")
    if prev["cvss_score"] != cur.cvss_score or prev["severity"] != cur.severity:
        types.append("severity_changed")
    if list(prev["cves"]) != list(cur.cves):
        types.append("aliases_changed")
    return types


def _signal_values(conn: Connection, advisory_id: str) -> dict[str, object]:
    row = conn.execute(
        text("SELECT kev, epss FROM v_advisories WHERE advisory_id = :a"), {"a": advisory_id}
    ).first()
    return {"kev": bool(row[0]), "epss": row[1]} if row else {}


def _record(
    conn: Connection, ctx: RunContext, advisory_id: str, types: list[str],
    prev: dict[str, object] | None, cur: AdvisoryState | None,
) -> None:
    ctx.changed += 1
    if not ctx.emit_events:
        return
    now = utc_now_iso()
    current = {**(cur.comparable() if cur else {}), **_signal_values(conn, advisory_id)}
    previous = prev or {}
    conn.execute(
        text("INSERT INTO advisory_history (advisory_id, change_types_json, previous_json, "
             "current_json, run_id, occurred_at) VALUES (:a, :t, :p, :c, :r, :o)"),
        {"a": advisory_id, "t": json.dumps(types), "p": json.dumps(previous, default=str),
         "c": json.dumps(current, default=str), "r": ctx.run_id, "o": now},
    )
    ctx.outbox.publish(
        conn,
        EVENT_ADVISORY_CHANGED,
        {
            "advisory_id": advisory_id,
            "change_types": types,
            "affected_purls": list(cur.affected_purls) if cur else [],
            "previous": previous,
            "current": current,
            "occurred_at": now,
        },
    )
    ctx.events += 1


def apply(conn: Connection, ctx: RunContext, advisory_id: str) -> list[str]:
    """advisory_id を再集計して保存し、変化があれば履歴とイベントを書く。"""
    prev = load_state(conn, advisory_id)
    cur = compute_state(conn, advisory_id)
    if cur is None:
        if prev is not None:
            delete_state(conn, advisory_id)
    else:
        save_state(conn, cur)
    detected = detect_changes(prev, cur)
    if SEVERITY_DEPENDENT_CHANGES.intersection(detected):
        mark_upstream_dependents(conn, advisory_id)
    types = detected + sorted(ctx.pop_signals(advisory_id))
    if types:
        _record(conn, ctx, advisory_id, types, prev, cur)
    return types


def apply_signals(conn: Connection, ctx: RunContext) -> None:
    """再集計の対象にならなかった KEV・EPSS だけの変化を記録する。"""
    for advisory_id in ctx.pending_signal_ids():
        apply(conn, ctx, advisory_id)
