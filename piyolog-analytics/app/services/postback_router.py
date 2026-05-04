"""Phase 2: リッチメニュー / クイックリプライからの Postback を action に振り分け。

Postback `data` は URL クエリ文字列形式。例:
    action=summary&period=today
    action=chart&kind=milk&period=week
    action=chart&kind=dashboard&period_from=2026-02-01&period_to=2026-02-28
    action=help
    action=undo
    action=consult&op=enter
    action=consult&op=exit
    action=settings                   # Phase 4-B: 設定 UI を開く
    action=child_set_birth_date       # datetime picker の params.date を保存
    action=child_set_name             # 名前入力モード開始 (text 待ち受け)
    action=settings_cancel            # 設定 UI を閉じる

未知の action / 不正パラメータは text fallback (UNKNOWN_HINT 等) で返す。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import parse_qs

from repositories.child_repo import ChildRepo, is_valid_birth_date
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
from services.line_client import QuickReplyAction

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_VALID_PERIODS = frozenset({"today", "yesterday", "week", "month"})

CONSULT_STUB_REPLY = (
    "💬 相談機能は Phase 3 で実装予定です。\n現在はサマリ・グラフ・取り込みのみ利用できます。"
)

# ---- Phase 4-B: 設定 UI ----

SETTINGS_PROMPT = (
    "⚙️ 設定メニュー\n"
    "下のボタンから変更したい項目を選んでください。"
)
SETTINGS_CANCELLED = "設定を閉じました。"
SETTINGS_NAME_PROMPT = (
    "✏️ 子の名前を変更します。\n"
    "「名前: たろう」のように送ってください (32 文字以内)。\n"
    "キャンセルする場合は「キャンセル」と送ってください。"
)
SETTINGS_BIRTH_DATE_INVALID = "日付の形式が不正でした。もう一度お試しください。"
SETTINGS_REPO_UNAVAILABLE = "設定機能は現在利用できません。少し時間を置いてからもう一度お試しください。"


def build_settings_quick_reply(*, current_birth_date: str | None) -> tuple[QuickReplyAction, ...]:
    """⚙️ 設定 UI 用の Quick Reply ボタン群を組み立てる。

    `current_birth_date` が DB に既登録なら datetime picker の `initial` に
    その値を入れ、未登録なら省略 (LINE 側で当日が選ばれる)。
    """
    return (
        QuickReplyAction(
            kind="datetimepicker",
            label="📅 子の生年月日",
            data="action=child_set_birth_date",
            mode="date",
            initial=current_birth_date if current_birth_date else None,
        ),
        QuickReplyAction(
            kind="postback",
            label="✏️ 子の名前",
            data="action=child_set_name",
        ),
        QuickReplyAction(
            kind="postback",
            label="キャンセル",
            data="action=settings_cancel",
        ),
    )


async def handle_postback(
    data: str,
    *,
    repo: EventRepo,
    family_id: str,
    now: datetime | None = None,
    postback_params: dict[str, str] | None = None,
    child_repo: ChildRepo | None = None,
    default_child_id: str = "default",
) -> CommandResult:
    """Postback `data` を解析して対応するアクションを実行。

    解析失敗・未知の action は UNKNOWN_HINT。

    Phase 4-B 追加: `postback_params` (datetime picker の date 等) と
    `child_repo` (children テーブルの DAO) を受け取る。Phase 2 / 3 までの
    呼び出し側との後方互換のため、両方とも optional。
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

    if action == "settings":
        return await _settings_open(
            child_repo=child_repo, family_id=family_id, default_child_id=default_child_id
        )

    if action == "settings_cancel":
        return CommandResult(reply=SETTINGS_CANCELLED)

    if action == "child_set_birth_date":
        return await _settings_set_birth_date(
            postback_params=postback_params or {},
            child_repo=child_repo,
            family_id=family_id,
            default_child_id=default_child_id,
        )

    if action == "child_set_name":
        # 実際の保存は line_handler 側のテキスト待ち受けで行う。
        return CommandResult(reply=SETTINGS_NAME_PROMPT)

    logger.info("unknown postback action: data=%r", data)
    return CommandResult(reply=UNKNOWN_HINT)


async def _settings_open(
    *, child_repo: ChildRepo | None, family_id: str, default_child_id: str
) -> CommandResult:
    """⚙️ 設定 UI: Quick Reply で 3 ボタンを返す。"""
    current_birth_date: str | None = None
    if child_repo is not None:
        try:
            child = await child_repo.get(family_id=family_id, child_id=default_child_id)
            if child and child.birth_date:
                current_birth_date = child.birth_date
        except Exception:
            logger.exception("failed to fetch child for settings open")
    return CommandResult(
        reply=SETTINGS_PROMPT,
        quick_reply=build_settings_quick_reply(current_birth_date=current_birth_date),
    )


async def _settings_set_birth_date(
    *,
    postback_params: dict[str, str],
    child_repo: ChildRepo | None,
    family_id: str,
    default_child_id: str,
) -> CommandResult:
    if child_repo is None:
        logger.warning("child_set_birth_date: child_repo not wired")
        return CommandResult(reply=SETTINGS_REPO_UNAVAILABLE)
    date_value = postback_params.get("date", "")
    if not is_valid_birth_date(date_value):
        return CommandResult(reply=SETTINGS_BIRTH_DATE_INVALID)
    try:
        await child_repo.upsert_birth_date(
            family_id=family_id, child_id=default_child_id, birth_date=date_value
        )
    except ValueError:
        return CommandResult(reply=SETTINGS_BIRTH_DATE_INVALID)
    except Exception:
        logger.exception("failed to upsert birth_date")
        return CommandResult(reply=SETTINGS_REPO_UNAVAILABLE)
    return CommandResult(reply=f"✅ 子の生年月日を {date_value} に設定しました。")


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
    "SETTINGS_BIRTH_DATE_INVALID",
    "SETTINGS_CANCELLED",
    "SETTINGS_NAME_PROMPT",
    "SETTINGS_PROMPT",
    "SETTINGS_REPO_UNAVAILABLE",
    "build_settings_quick_reply",
    "handle_postback",
]
