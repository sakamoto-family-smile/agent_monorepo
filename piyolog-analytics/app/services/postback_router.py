"""Phase 2: リッチメニュー / クイックリプライからの Postback を action に振り分け。

Postback `data` は URL クエリ文字列形式。例:
    action=summary&period=today
    action=chart&kind=milk&period=week
    action=chart&kind=dashboard&period_from=2026-02-01&period_to=2026-02-28
    action=help
    action=undo
    action=consult&op=enter        # Phase 3 stub
    action=consult&op=exit         # Phase 3 stub

未知の action / 不正パラメータは text fallback (UNKNOWN_HINT 等) で返す。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import parse_qs

from repositories.event_repo import EventRepo
from services.analytics import resolve_period
from services.command_router import (
    CHART_KINDS,
    CHART_NO_DATA_HINT,
    HELP_TEXT,
    INVALID_PERIOD_HINT,
    UNDO_NO_BATCH_HINT,
    UNKNOWN_HINT,
    CommandResult,
    render_chart,
    render_summary,
)

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_VALID_PERIODS = frozenset({"today", "yesterday", "week", "month"})

CONSULT_STUB_REPLY = (
    "💬 相談機能は Phase 3 で実装予定です。\n現在はサマリ・グラフ・取り込みのみ利用できます。"
)


async def handle_postback(
    data: str,
    *,
    repo: EventRepo,
    family_id: str,
    now: datetime | None = None,
) -> CommandResult:
    """Postback `data` を解析して対応するアクションを実行。

    解析失敗・未知の action は UNKNOWN_HINT。
    """
    params = _parse_data(data)
    action = params.get("action", "")

    if action == "help":
        return CommandResult(reply=HELP_TEXT)

    if action == "undo":
        batch = await repo.rollback_latest_batch(family_id=family_id)
        if batch is None:
            return CommandResult(reply=UNDO_NO_BATCH_HINT)
        filename = batch.source_filename or "(no name)"
        msg = (
            "🔄 直近の取り込みを取り消しました。\n"
            f"ファイル: {filename}\n"
            f"件数: {batch.event_count} 件"
        )
        return CommandResult(reply=msg)

    if action == "summary":
        period = params.get("period", "today")
        return await _summary_action(params, period=period, repo=repo, family_id=family_id, now=now)

    if action == "chart":
        kind = params.get("kind", "")
        if kind not in CHART_KINDS:
            return CommandResult(reply=UNKNOWN_HINT)
        return await _chart_action(params, kind=kind, repo=repo, family_id=family_id, now=now)

    if action == "consult":
        # Phase 3 で実装予定。今は stub。
        return CommandResult(reply=CONSULT_STUB_REPLY)

    logger.info("unknown postback action: data=%r", data)
    return CommandResult(reply=UNKNOWN_HINT)


def _parse_data(data: str) -> dict[str, str]:
    """`a=1&b=2` を flat dict に。同一 key 複数なら最初のもののみ。"""
    qs = parse_qs(data, keep_blank_values=True)
    return {k: (v[0] if v else "") for k, v in qs.items()}


async def _summary_action(
    params: dict[str, str],
    *,
    period: str,
    repo: EventRepo,
    family_id: str,
    now: datetime | None,
) -> CommandResult:
    if period == "period":
        pf = params.get("period_from", "")
        pt = params.get("period_to", "")
        if not (_DATE_RE.match(pf) and _DATE_RE.match(pt)):
            return CommandResult(reply=INVALID_PERIOD_HINT)
        return await render_summary(
            period="period",
            repo=repo,
            family_id=family_id,
            now=now,
            custom_from=pf,
            custom_to=pt,
        )
    if period not in _VALID_PERIODS:
        return CommandResult(reply=UNKNOWN_HINT)
    return await render_summary(period=period, repo=repo, family_id=family_id, now=now)


async def _chart_action(
    params: dict[str, str],
    *,
    kind: str,
    repo: EventRepo,
    family_id: str,
    now: datetime | None,
) -> CommandResult:
    """chart アクションで `period` (preset) または `period_from/to` (custom) を解析。

    どちらも無ければ default を kind に応じて決める (week / month)。
    """
    pf = params.get("period_from", "")
    pt = params.get("period_to", "")
    if pf or pt:
        if not (_DATE_RE.match(pf) and _DATE_RE.match(pt)):
            return CommandResult(reply=INVALID_PERIOD_HINT)
        try:
            date_from, date_to, label = resolve_period(
                "period", now=now, custom_from=pf, custom_to=pt
            )
        except ValueError:
            return CommandResult(reply=INVALID_PERIOD_HINT)
    else:
        period = params.get("period", "")
        if not period:
            period = "month" if kind in {"weight", "heatmap"} else "week"
        if period not in _VALID_PERIODS:
            return CommandResult(reply=UNKNOWN_HINT)
        date_from, date_to, label = resolve_period(period, now=now)

    return await render_chart(
        chart_kind=kind,
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
        label=label,
        repo=repo,
        family_id=family_id,
    )


__all__ = [
    "CHART_NO_DATA_HINT",
    "CONSULT_STUB_REPLY",
    "handle_postback",
]
