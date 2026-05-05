"""LINE Webhook イベントをパースしてコマンドにディスパッチする。

本モジュールは LINE SDK に直接依存しない:
  - 入力: `LineTextEvent` / `LineFileEvent` (services/line_client.py 定義の内製 DTO)
  - 出力: `LineBotClient.reply_text()` を呼び出し、必要なら DB を更新
  - LLM は既存の `run_chat` を再利用
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from agents.csv_importer import parse_bytes
from agents.orchestrator import run_chat
from repositories.household import ensure_household
from repositories.line_link import create_link, delete_link, get_link
from repositories.scenario import get_scenario_for_household, list_scenarios
from repositories.transaction import upsert_transactions
from services.anomalies import detect_anomalies
from services.line_client import (
    LineBotClient,
    LineEvent,
    LineFileEvent,
    LineTextEvent,
)
from services.line_flex import (
    anomalies_bubble,
    narrative_bubble,
    networth_bubble,
    scenarios_carousel,
    summary_bubble,
)
from services.line_period import (
    parse_date_arg,
    parse_month_arg,
    parse_summary_period,
)
from services.llm_client import LLMClient
from services.networth import compute_networth
from services.summary import compute_summary
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# コマンド文面 (定数)
# ---------------------------------------------------------------------------

HELP_TEXT = (
    "【ライフプランナー Bot コマンド】\n"
    "■ 連携\n"
    "/help — このヘルプ\n"
    "/whoami — 連携状態を表示\n"
    "/invite — 配偶者に共有するコマンドを表示\n"
    "/link <世帯ID> — 既存の世帯に参加\n"
    "/unlink — 自分の連携を解除\n"
    "\n"
    "■ 分析 (PR 2)\n"
    "/summary [今月|先月|今年|YYYY-MM YYYY-MM] — 月次サマリ\n"
    "/networth [YYYY-MM-DD] — 純資産 (資産・負債内訳)\n"
    "/anomalies [YYYY-MM] — 3σ 異常検知 (直近 6 ヶ月平均との比較)\n"
    "\n"
    "■ シナリオ\n"
    "/scenarios — シナリオ一覧\n"
    "/summarize <id> — シナリオの要約\n"
    "/compare <id1> <id2> [...] — シナリオ比較 (最大5件)\n"
    "\n"
    "■ 取り込み\n"
    "CSV を送ると家計データとして取り込みます"
)

UNKNOWN_COMMAND_HINT = (
    "認識できない入力でした。/help でコマンド一覧を見られます。"
)

NEED_LINK_HINT = (
    "まだ世帯に連携されていません。何か一言送ると新しい世帯を自動作成します。"
)


# ---------------------------------------------------------------------------
# 依存バンドル
# ---------------------------------------------------------------------------


@dataclass
class HandlerDeps:
    session: AsyncSession
    line_client: LineBotClient
    llm_client: LLMClient


# ---------------------------------------------------------------------------
# リプライヘルパ (Flex → 失敗時に text にフォールバック)
# ---------------------------------------------------------------------------


async def _reply_flex_or_text(
    deps: HandlerDeps,
    *,
    reply_token: str,
    text: str,
    flex_contents: dict,
    alt_text: str,
) -> None:
    """Flex を試し、失敗したら text に退避する。SDK バージョン差異や JSON 構造エラーに備える。"""
    try:
        await deps.line_client.reply_flex(
            reply_token=reply_token, alt_text=alt_text, contents=flex_contents
        )
        return
    except Exception:
        logger.exception("reply_flex failed; falling back to reply_text")
    await deps.line_client.reply_text(reply_token=reply_token, text=text)


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------


async def handle_event(event: LineEvent, deps: HandlerDeps) -> None:
    """単一イベントをディスパッチ。例外は呼び出し元 (route) で拾ってログに残す。"""
    if isinstance(event, LineTextEvent):
        await _handle_text(event, deps)
    elif isinstance(event, LineFileEvent):
        await _handle_file(event, deps)
    else:
        logger.warning("Unhandled event type: %r", event)


# ---------------------------------------------------------------------------
# テキストイベント
# ---------------------------------------------------------------------------


async def _handle_text(event: LineTextEvent, deps: HandlerDeps) -> None:
    raw = event.text.strip()
    link = await get_link(deps.session, event.line_user_id)

    if raw.startswith("/"):
        await _dispatch_command(raw, link, event, deps)
        return

    # コマンドではない自然文
    if link is None:
        # 初回接触 → 自動連携
        await _auto_link(event, deps)
        return

    await deps.line_client.reply_text(
        reply_token=event.reply_token, text=UNKNOWN_COMMAND_HINT
    )


async def _dispatch_command(
    raw: str,
    link,  # LineUserLink | None
    event: LineTextEvent,
    deps: HandlerDeps,
) -> None:
    parts = raw.split()
    cmd, args = parts[0], parts[1:]

    if cmd == "/help":
        await deps.line_client.reply_text(
            reply_token=event.reply_token, text=HELP_TEXT
        )
        return

    if cmd == "/link":
        await _cmd_link(args, link, event, deps)
        return

    # /help と /link 以外は連携必須
    if link is None:
        await deps.line_client.reply_text(
            reply_token=event.reply_token, text=NEED_LINK_HINT
        )
        return

    if cmd == "/whoami":
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text=f"LINE userId={event.line_user_id}\n世帯ID={link.household_id}",
        )
        return

    if cmd == "/invite":
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text=(
                "配偶者に以下のコマンドを送ってもらってください:\n"
                f"/link {link.household_id}"
            ),
        )
        return

    if cmd == "/unlink":
        await delete_link(deps.session, event.line_user_id)
        await deps.session.commit()
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text="連携を解除しました。/help で利用可能なコマンドを確認できます。",
        )
        return

    if cmd == "/scenarios":
        await _cmd_scenarios(event, link, deps)
        return

    if cmd == "/summarize":
        await _cmd_summarize(args, event, link, deps)
        return

    if cmd == "/compare":
        await _cmd_compare(args, event, link, deps)
        return

    # PR 2: 分析コマンド
    if cmd == "/summary":
        await _cmd_summary(args, event, link, deps)
        return

    if cmd == "/networth":
        await _cmd_networth(args, event, link, deps)
        return

    if cmd == "/anomalies":
        await _cmd_anomalies(args, event, link, deps)
        return

    await deps.line_client.reply_text(
        reply_token=event.reply_token, text=UNKNOWN_COMMAND_HINT
    )


# ---------------------------------------------------------------------------
# コマンド実装
# ---------------------------------------------------------------------------


def _generate_household_id() -> str:
    # 24 文字程度にしておくと LINE 上で扱いやすい
    return f"line-{uuid.uuid4().hex[:20]}"


async def _auto_link(event: LineTextEvent, deps: HandlerDeps) -> None:
    household_id = _generate_household_id()
    await ensure_household(deps.session, household_id, name=f"LINE {household_id}")
    await create_link(
        deps.session, line_user_id=event.line_user_id, household_id=household_id
    )
    await deps.session.commit()
    await deps.line_client.reply_text(
        reply_token=event.reply_token,
        text=(
            "はじめまして。新しい世帯を作成し、あなたを紐付けました。\n"
            f"世帯ID: {household_id}\n\n"
            "配偶者と共有する場合は /invite を送ってください。\n"
            "CSV を送るとこの世帯に取り込まれます。\n"
            "/help でコマンド一覧を確認できます。"
        ),
    )


async def _cmd_link(
    args: list[str],
    link,  # LineUserLink | None
    event: LineTextEvent,
    deps: HandlerDeps,
) -> None:
    if link is not None:
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text=(
                f"既に世帯 {link.household_id} に連携済みです。"
                "他の世帯に移る場合は /unlink してから再度 /link してください。"
            ),
        )
        return

    if len(args) != 1:
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text="使い方: /link <世帯ID>",
        )
        return

    household_id = args[0]
    # 既存チェック — 存在しない世帯への紐付けは禁止
    from repositories.household import get_household

    existing = await get_household(deps.session, household_id)
    if existing is None:
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text=f"世帯 {household_id} は見つかりませんでした。",
        )
        return

    await create_link(
        deps.session, line_user_id=event.line_user_id, household_id=household_id
    )
    await deps.session.commit()
    await deps.line_client.reply_text(
        reply_token=event.reply_token,
        text=f"世帯 {household_id} に参加しました。",
    )


async def _cmd_scenarios(
    event: LineTextEvent,
    link,
    deps: HandlerDeps,
) -> None:
    scenarios = await list_scenarios(deps.session, link.household_id)
    if not scenarios:
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text=(
                "シナリオがまだ登録されていません。"
                "Web API 経由で作成してから /summarize / /compare を利用してください。"
            ),
        )
        return

    # Flex carousel (最大 10 件)。alt_text / text フォールバックは同内容で統一。
    summary_lines = [f"{s.id}: {s.name}" for s in scenarios]
    text_fallback = "シナリオ一覧:\n" + "\n".join(summary_lines)
    alt_text = "シナリオ一覧: " + ", ".join(summary_lines[:5])

    flex = scenarios_carousel(
        [(s.id, s.name, s.description) for s in scenarios]
    )
    await _reply_flex_or_text(
        deps,
        reply_token=event.reply_token,
        text=text_fallback,
        flex_contents=flex,
        alt_text=alt_text,
    )


async def _cmd_summarize(
    args: list[str],
    event: LineTextEvent,
    link,
    deps: HandlerDeps,
) -> None:
    if len(args) != 1 or not args[0].isdigit():
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text="使い方: /summarize <scenario_id>",
        )
        return
    await _run_chat_reply(
        event=event,
        deps=deps,
        household_id=link.household_id,
        scenario_ids=[int(args[0])],
    )


async def _cmd_compare(
    args: list[str],
    event: LineTextEvent,
    link,
    deps: HandlerDeps,
) -> None:
    if len(args) < 2 or not all(a.isdigit() for a in args):
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text="使い方: /compare <id1> <id2> [...最大5つ]",
        )
        return
    ids = [int(a) for a in args][:5]
    await _run_chat_reply(
        event=event,
        deps=deps,
        household_id=link.household_id,
        scenario_ids=ids,
    )


async def _run_chat_reply(
    *,
    event: LineTextEvent,
    deps: HandlerDeps,
    household_id: str,
    scenario_ids: list[int],
) -> None:
    try:
        result = await run_chat(
            session=deps.session,
            household_id=household_id,
            scenario_ids=scenario_ids,
            question=None,
            llm=deps.llm_client,
        )
    except ValueError as e:
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text=f"エラー: {e}",
        )
        return

    # 見出し用にシナリオ名を取得する。run_chat が成功している以上、
    # いずれの ID も世帯に存在することは保証されているが、念のため None 防御する。
    names: list[str] = []
    for sid in scenario_ids:
        sc = await get_scenario_for_household(deps.session, sid, household_id)
        names.append(sc.name if sc is not None else f"#{sid}")

    if len(names) == 1:
        title = f"{names[0]} の要約"
    else:
        title = f"比較: {names[0]} vs " + ", ".join(names[1:])

    flex = narrative_bubble(title=title, body_text=result.narrative)
    # alt_text は通知プレビュー用。narrative の先頭を挿れる。
    alt_text = f"{title}: {result.narrative[:200]}"
    await _reply_flex_or_text(
        deps,
        reply_token=event.reply_token,
        text=result.narrative,
        flex_contents=flex,
        alt_text=alt_text,
    )


# ---------------------------------------------------------------------------
# PR 2: 分析コマンド
# ---------------------------------------------------------------------------


async def _cmd_summary(
    args: list[str], event: LineTextEvent, link, deps: HandlerDeps
) -> None:
    """`/summary [今月|先月|今年|YYYY-MM YYYY-MM]` — 月次サマリ。"""
    try:
        period = parse_summary_period(args)
    except ValueError as e:
        await deps.line_client.reply_text(
            reply_token=event.reply_token, text=f"使い方エラー: {e}"
        )
        return

    summary = await compute_summary(
        deps.session,
        link.household_id,
        start=period.start,
        end=period.end,
        top_categories=5,
    )
    top = [(c.category, c.expense) for c in summary.categories[:5]]
    text_fallback = (
        f"📊 サマリ ({period.label})\n"
        f"収入 {int(summary.total_income):,} / "
        f"支出 {int(summary.total_expense):,} / "
        f"ネット {int(summary.net):+,}\n"
        f"貯蓄率 {summary.savings_rate * 100:.1f}%"
    )
    flex = summary_bubble(
        period_label=period.label,
        total_income=summary.total_income,
        total_expense=summary.total_expense,
        net=summary.net,
        savings_rate=summary.savings_rate,
        fixed=summary.expense_types.fixed,
        variable=summary.expense_types.variable,
        top_categories=top,
    )
    await _reply_flex_or_text(
        deps,
        reply_token=event.reply_token,
        text=text_fallback,
        flex_contents=flex,
        alt_text=f"サマリ {period.label}",
    )


async def _cmd_networth(
    args: list[str], event: LineTextEvent, link, deps: HandlerDeps
) -> None:
    """`/networth [YYYY-MM-DD]` — 純資産。"""
    try:
        as_of, label = parse_date_arg(args[0] if args else None)
    except ValueError as e:
        await deps.line_client.reply_text(
            reply_token=event.reply_token, text=f"使い方エラー: {e}"
        )
        return

    nw = await compute_networth(deps.session, link.household_id, as_of=as_of)
    text_fallback = (
        f"💰 純資産 ({label} 時点)\n"
        f"総資産 {int(nw.current.total_assets):,} / "
        f"総負債 {int(nw.current.total_liabilities):,}\n"
        f"純資産 {int(nw.current.net_worth):,}"
    )
    flex = networth_bubble(
        as_of_label=label,
        total_assets=nw.current.total_assets,
        total_liabilities=nw.current.total_liabilities,
        net_worth=nw.current.net_worth,
        by_kind_assets=nw.by_kind_assets,
        by_kind_liabilities=nw.by_kind_liabilities,
    )
    await _reply_flex_or_text(
        deps,
        reply_token=event.reply_token,
        text=text_fallback,
        flex_contents=flex,
        alt_text=f"純資産 {label}",
    )


async def _cmd_anomalies(
    args: list[str], event: LineTextEvent, link, deps: HandlerDeps
) -> None:
    """`/anomalies [YYYY-MM]` — 3σ 異常検知。"""
    try:
        target_month, label = parse_month_arg(args[0] if args else None)
    except ValueError as e:
        await deps.line_client.reply_text(
            reply_token=event.reply_token, text=f"使い方エラー: {e}"
        )
        return

    history_months = 6
    anomalies = await detect_anomalies(
        deps.session,
        link.household_id,
        target_month=target_month,
        history_months=history_months,
    )
    rows = [(a.canonical_category, a.expense, a.mean, a.z_score) for a in anomalies]
    if not anomalies:
        text_fallback = (
            f"⚠️ 異常検知 ({label})\n"
            f"過去 {history_months} ヶ月平均から 3σ 超のカテゴリはありません。"
        )
    else:
        head = "\n".join(
            f"・{a.canonical_category}: {int(a.expense):,} 円 (z={a.z_score:.1f}σ)"
            for a in anomalies[:5]
        )
        text_fallback = f"⚠️ 異常検知 ({label})\n{head}"

    flex = anomalies_bubble(
        target_month_label=label,
        anomalies=rows,
        history_months=history_months,
    )
    await _reply_flex_or_text(
        deps,
        reply_token=event.reply_token,
        text=text_fallback,
        flex_contents=flex,
        alt_text=f"異常検知 {label}",
    )


# ---------------------------------------------------------------------------
# ファイルイベント (CSV 取込)
# ---------------------------------------------------------------------------

_MAX_LINE_FILE_BYTES = 5 * 1024 * 1024  # 5MB (/api/upload と揃える)


async def _handle_file(event: LineFileEvent, deps: HandlerDeps) -> None:
    link = await get_link(deps.session, event.line_user_id)
    if link is None:
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text=(
                "ファイルを受け取るには先に世帯連携が必要です。"
                "何か一言送ると自動で世帯を作成します。"
            ),
        )
        return

    if event.file_size > _MAX_LINE_FILE_BYTES:
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text=f"ファイルが大きすぎます ({event.file_size} bytes)。5MB 以下にしてください。",
        )
        return

    content = await deps.line_client.get_message_content(message_id=event.message_id)

    try:
        imported = parse_bytes(content, source_label=event.file_name)
    except ValueError as e:
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text=f"CSV の解析に失敗しました: {e}",
        )
        return

    await ensure_household(deps.session, link.household_id, name=link.household_id)
    upsert = await upsert_transactions(
        deps.session, link.household_id, imported.transactions
    )
    await deps.session.commit()

    await deps.line_client.reply_text(
        reply_token=event.reply_token,
        text=(
            f"CSV 取り込み完了: {event.file_name}\n"
            f"読み込み {imported.imported} 件 / 追加 {upsert.inserted} 件 / "
            f"更新 {upsert.updated} 件 / 変更なし {upsert.unchanged} 件"
        ),
    )
