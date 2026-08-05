"""LINE Webhook イベントをパースしてコマンドにディスパッチする。

設計方針:
  - LINE SDK には直接依存しない (services.line_client の DTO のみ)
  - 株価分析エージェントは `stock-analysis-agent` 内にあるので
    `/api/funds/recommend` 等を HTTP 経由で呼ぶのではなく、対応する関数を
    直接 import して呼び出す (低レイテンシ・テスト容易性のため)
  - 同期コマンド (ヘルプ / おすすめ / スクリーニング) は Reply API でその場で返す
  - 非同期コマンド (分析) は ack を Reply で返した後、`schedule_analysis()` 経由で
    バックグラウンドタスクから Push API で結果送信する
    (Reply token は約1分で失効、Claude 分析は数十秒〜数分かかるため)
  - 状態は持たない (stateless): 履歴 / お気に入り銘柄等は Phase C で扱う
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from agents.fund_screener import run_fund_recommend
from agents.orchestrator import run_analysis
from agents.screener import run_screener
from agents.ticker_resolver import (
    fetch_ticker_name,
    resolve_ticker,
    search_candidates,
)
from services.database import (
    add_watchlist_item,
    count_watchlist,
    get_watchlist,
    remove_watchlist_item,
)
import config  # NOTE: `from config import settings` だと importlib.reload 後の
# 新 settings を参照できず test isolation が壊れる (database.py と同方針)。
from models.stock import (
    AnalysisRequest,
    FundRecommendRequest,
    ScreenerRequest,
)
from services.access_control import get_analyze_limiter, is_user_allowed
from services.media import store_chart_png, store_report_html, store_report_md
from services.task_queue import enqueue_analysis
from services.line_client import (
    LineBotClient,
    LineEvent,
    LineTextEvent,
)
from services.line_flex import (
    analysis_summary_bubble,
    funds_ranking_carousel,
    screener_ranking_carousel,
    ticker_candidates_bubble,
    watchlist_bubble,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# コマンド文面
# ---------------------------------------------------------------------------

# 分析所要時間の目安。EDINET 有効時は有報 PDF/XBRL の取得・読解が入り長くなる。
_ETA_WITH_EDINET = "1〜5分"
_ETA_WITHOUT_EDINET = "30秒〜2分"


def _analyze_eta() -> str:
    return _ETA_WITH_EDINET if config.settings.edinet_enabled else _ETA_WITHOUT_EDINET


def _help_text() -> str:
    return (
        "【株価分析エージェント Bot】\n"
        "■ ヘルプ\n"
        "  ・ヘルプ — このメッセージ\n"
        "■ 投資信託 (ETF) のオススメ\n"
        "  ・おすすめ — 全カテゴリ Top5\n"
        "  ・おすすめ 米国 — S&P500 / VTI / QQQ など\n"
        "  ・おすすめ 世界 — VT / ACWI / VEA など\n"
        "  ・おすすめ 配当 — SCHD / VYM など\n"
        "  ・おすすめ セクター — XLK / SOXX / XLF など\n"
        "■ 短期上昇候補スクリーニング\n"
        "  ・スクリーニング — 日本株を上位10件\n"
        "  ・スクリーニング JP / US / ALL\n"
        f"■ 個別株分析 (分析開始から完了まで {_analyze_eta()})\n"
        "  ・分析 トヨタ\n"
        "  ・分析 AAPL\n"
        "  ・分析 7203.T\n"
        "■ マイリスト (お気に入り銘柄)\n"
        "  ・追加 トヨタ / 追加 AAPL — マイリストに追加\n"
        "  ・削除 7203.T — マイリストから削除\n"
        "  ・マイリスト — 一覧を表示\n"
        "  ・スクリーニング マイ — マイリストをスクリーニング\n"
        "■ その他\n"
        "  ・ID — 自分のユーザーID を表示 (利用登録用)\n\n"
        "※ 投資判断はご自身の責任でお願いします。"
    )


UNKNOWN_HINT = "認識できない入力でした。「ヘルプ」と送るとコマンド一覧を表示します。"

DISCLAIMER_SHORT = (
    "※ 情報提供のみを目的としており、投資勧誘・個別の助言ではありません。"
)

ANALYZE_ACK_TEMPLATE = (
    "📊 {target} の分析を開始しました。\n"
    "完了まで {eta}ほどかかります。完了次第、結果をお送りします。"
)

ANALYZE_FAIL_TEMPLATE = (
    "⚠️ {target} の分析に失敗しました: {reason}\n"
    "時間を置いて再度お試しください。"
)

ANALYZE_RATE_LIMITED_TEXT = (
    "🚦 本日の分析回数の上限に達しました。\n"
    "明日また分析できます (おすすめ / スクリーニングは引き続き利用可能)。"
)


# ---------------------------------------------------------------------------
# 依存バンドル
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnalyzeResult:
    """分析結果の配信に必要な素材。

    report_text は Claude が生成した全文 (Markdown)、chart_path は mplfinance が
    出力したローソク足 PNG のローカルパス (無い場合は None)。
    recommendation は `BuyRecommendation.model_dump()` (パース不能時は None)。
    """

    ticker: str
    company_name: str | None
    report_text: str
    chart_path: str | None = None
    recommendation: dict | None = None


# AnalyzeRunner: テストで差し替えやすいよう、orchestrator の呼び出しを
# 関数差し込みできるようにする
AnalyzeRunner = Callable[[AnalysisRequest], "Awaitable[AnalyzeResult]"]


@dataclass
class HandlerDeps:
    line_client: LineBotClient
    # 非同期 analyze をバックグラウンドで実行する schedule 関数。
    # FastAPI の BackgroundTasks か asyncio.create_task のどちらでも良い。
    schedule_background: Callable[[Callable[[], Awaitable[None]]], None]
    analyze_runner: AnalyzeRunner | None = None  # None なら標準 run_analysis を使う


# ---------------------------------------------------------------------------
# Reply ヘルパ (Flex を試し失敗時 text にフォールバック)
# ---------------------------------------------------------------------------


async def _reply_flex_or_text(
    deps: HandlerDeps,
    *,
    reply_token: str,
    fallback_text: str,
    flex_contents: dict,
    alt_text: str,
) -> None:
    try:
        await deps.line_client.reply_flex(
            reply_token=reply_token, alt_text=alt_text, contents=flex_contents
        )
        return
    except Exception:
        logger.exception("reply_flex failed; falling back to reply_text")
    await deps.line_client.reply_text(reply_token=reply_token, text=fallback_text)


async def _push_flex_or_text(
    deps: HandlerDeps,
    *,
    to: str,
    fallback_text: str,
    flex_contents: dict,
    alt_text: str,
) -> None:
    try:
        await deps.line_client.push_flex(
            to=to, alt_text=alt_text, contents=flex_contents
        )
        return
    except Exception:
        logger.exception("push_flex failed; falling back to push_text")
    await deps.line_client.push_text(to=to, text=fallback_text)


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------


async def handle_event(event: LineEvent, deps: HandlerDeps) -> None:
    """単一イベントをディスパッチ。例外は呼び出し元 (route) で拾ってログに残す。"""
    if isinstance(event, LineTextEvent):
        await _handle_text(event, deps)
    else:
        logger.warning("Unhandled event type: %r", event)


# ---------------------------------------------------------------------------
# 入力正規化
# ---------------------------------------------------------------------------


def _normalize_command(raw: str) -> tuple[str, list[str]]:
    """先頭の空白除去 + 全角空白を半角化 + slash プレフィックス除去。

    戻り値: (cmd_word, args)
    """
    # 全角空白 → 半角
    s = raw.replace("\u3000", " ").strip()
    # /command 形式も受ける
    if s.startswith("/"):
        s = s[1:]
    parts = s.split()
    if not parts:
        return ("", [])
    return (parts[0], parts[1:])


_HELP_TOKENS = {"ヘルプ", "help", "menu", "メニュー", "?", "？"}
_RECOMMEND_TOKENS = {"おすすめ", "オススメ", "お勧め", "recommend", "funds"}
_SCREEN_TOKENS = {"スクリーニング", "screen", "screener"}
_ANALYZE_TOKENS = {"分析", "analyze", "analysis"}
# PROPOSAL-0012: マイリスト
_WATCHLIST_ADD_TOKENS = {"追加", "銘柄追加", "ウォッチ", "watch", "add"}
_WATCHLIST_REMOVE_TOKENS = {"削除", "銘柄削除", "unwatch", "remove", "del"}
_WATCHLIST_SHOW_TOKENS = {"マイリスト", "リスト", "watchlist", "お気に入り", "ウォッチリスト"}
# 自分の userId を返すコマンド (家族/友人を allow-list に追加する登録動線)。
# LINE アプリでは Messaging API の userId をユーザー本人が確認できないため、
# Bot にこのコマンドを送ってもらい、返ってきた ID を管理者へ伝えてもらう。
_WHOAMI_TOKENS = {"id", "ユーザーid", "userid", "whoami", "登録"}

WHOAMI_TEMPLATE = (
    "🪪 あなたのユーザーID:\n{user_id}\n\n"
    "この Bot の利用登録を希望する場合は、上の ID を管理者へ伝えてください。"
)

_CATEGORY_ALIASES: dict[str, str] = {
    "米国": "us_index", "米国株": "us_index", "us": "us_index",
    "us_index": "us_index", "sp500": "us_index", "s&p500": "us_index",
    "世界": "global", "全世界": "global", "global": "global",
    "オルカン": "global",
    "配当": "dividend", "高配当": "dividend", "dividend": "dividend",
    "セクター": "sector", "sector": "sector",
    "all": "all", "全部": "all",
}

_MARKET_ALIASES: dict[str, str] = {
    "jp": "JP", "日本": "JP", "日本株": "JP",
    "us": "US", "米国": "US", "米国株": "US",
    "all": "ALL", "全部": "ALL",
    "growth": "GROWTH", "成長": "GROWTH",
    "マイ": "MY", "my": "MY", "マイリスト": "MY", "watchlist": "MY",
}


# ---------------------------------------------------------------------------
# テキストイベント
# ---------------------------------------------------------------------------


async def _handle_text(event: LineTextEvent, deps: HandlerDeps) -> None:
    cmd, args = _normalize_command(event.text)
    cmd_lower = cmd.lower()

    # whoami は allow-list 適用外 (新メンバーが自分の userId を知る唯一の動線)。
    # 送信者自身の ID を返すだけで LLM も呼ばないため、開放しても実害なし。
    if cmd and (cmd in _WHOAMI_TOKENS or cmd_lower in _WHOAMI_TOKENS):
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text=WHOAMI_TEMPLATE.format(user_id=event.line_user_id),
        )
        return

    # allow-list: FAMILY_USER_IDS 設定時は家族以外を無視 (返信せず黙殺)。
    # public webhook + Claude Opus 課金の濫用を防ぐ (PROPOSAL-0011 §3.4)。
    if not is_user_allowed(event.line_user_id):
        logger.info("ignoring message from non-allowlisted user")
        return

    if not cmd:
        await deps.line_client.reply_text(reply_token=event.reply_token, text=UNKNOWN_HINT)
        return

    if cmd in _HELP_TOKENS or cmd_lower in _HELP_TOKENS:
        await deps.line_client.reply_text(reply_token=event.reply_token, text=_help_text())
        return

    if cmd in _RECOMMEND_TOKENS or cmd_lower in _RECOMMEND_TOKENS:
        await _cmd_recommend(args, event, deps)
        return

    if cmd in _SCREEN_TOKENS or cmd_lower in _SCREEN_TOKENS:
        await _cmd_screen(args, event, deps)
        return

    if cmd in _ANALYZE_TOKENS or cmd_lower in _ANALYZE_TOKENS:
        await _cmd_analyze(args, event, deps)
        return

    if cmd in _WATCHLIST_ADD_TOKENS or cmd_lower in _WATCHLIST_ADD_TOKENS:
        await _cmd_watchlist_add(args, event, deps)
        return

    if cmd in _WATCHLIST_REMOVE_TOKENS or cmd_lower in _WATCHLIST_REMOVE_TOKENS:
        await _cmd_watchlist_remove(args, event, deps)
        return

    if cmd in _WATCHLIST_SHOW_TOKENS or cmd_lower in _WATCHLIST_SHOW_TOKENS:
        await _cmd_watchlist_show(event, deps)
        return

    await deps.line_client.reply_text(reply_token=event.reply_token, text=UNKNOWN_HINT)


# ---------------------------------------------------------------------------
# /おすすめ
# ---------------------------------------------------------------------------


async def _cmd_recommend(
    args: list[str], event: LineTextEvent, deps: HandlerDeps
) -> None:
    category = "all"
    if args:
        token = args[0].lower()
        category = _CATEGORY_ALIASES.get(token, _CATEGORY_ALIASES.get(args[0], "all"))

    req = FundRecommendRequest(category=category, top_n=5, horizon="1y")
    try:
        result = await run_fund_recommend(req)
    except Exception as e:
        logger.exception("fund recommend failed")
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text=f"おすすめ取得に失敗しました: {e}",
        )
        return

    if not result.candidates:
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text=(
                f"カテゴリ '{category}' で対象ファンドが見つかりませんでした。\n"
                "「ヘルプ」でカテゴリ一覧を確認できます。"
            ),
        )
        return

    candidates = [c.model_dump(mode="json") for c in result.candidates]
    flex = funds_ranking_carousel(candidates)
    fallback_lines = [
        f"#{c['rank']} {c['ticker']} ({c.get('name') or ''}) スコア{c['score']}"
        for c in candidates
    ]
    fallback_text = (
        f"投資信託おすすめランキング ({category} / 1y)\n"
        + "\n".join(fallback_lines)
        + f"\n\n{DISCLAIMER_SHORT}"
    )
    alt_text = f"おすすめ {category}: " + ", ".join(c["ticker"] for c in candidates)

    await _reply_flex_or_text(
        deps,
        reply_token=event.reply_token,
        fallback_text=fallback_text,
        flex_contents=flex,
        alt_text=alt_text,
    )


# ---------------------------------------------------------------------------
# /スクリーニング
# ---------------------------------------------------------------------------


async def _cmd_screen(
    args: list[str], event: LineTextEvent, deps: HandlerDeps
) -> None:
    market = "JP"
    if args:
        token = args[0].lower()
        market = _MARKET_ALIASES.get(token, _MARKET_ALIASES.get(args[0], "JP"))

    # PROPOSAL-0012: market=MY はユーザーのマイリストを対象にする。
    tickers: list[str] | None = None
    if market == "MY":
        items = await get_watchlist(event.line_user_id)
        tickers = [it["ticker"] for it in items]
        if not tickers:
            await deps.line_client.reply_text(
                reply_token=event.reply_token,
                text=(
                    "マイリストが空です。「追加 トヨタ」「追加 AAPL」のように"
                    "銘柄を登録してから「スクリーニング マイ」をお試しください。"
                ),
            )
            return

    req = ScreenerRequest(market=market, top_n=10, tickers=tickers)
    try:
        result = await run_screener(req)
    except Exception as e:
        logger.exception("screener failed")
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text=f"スクリーニングに失敗しました: {e}",
        )
        return

    if not result.candidates:
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text=f"市場 {market} で条件を満たす銘柄がありませんでした。",
        )
        return

    candidates = [c.model_dump(mode="json") for c in result.candidates]
    flex = screener_ranking_carousel(candidates)
    fallback_lines = [
        f"#{c['rank']} {c['ticker']} スコア{c['score']}"
        for c in candidates
    ]
    fallback_text = (
        f"短期上昇候補 ({market}, scanned={result.total_scanned})\n"
        + "\n".join(fallback_lines)
        + f"\n\n{DISCLAIMER_SHORT}"
    )
    alt_text = f"スクリーニング {market}: " + ", ".join(c["ticker"] for c in candidates)

    await _reply_flex_or_text(
        deps,
        reply_token=event.reply_token,
        fallback_text=fallback_text,
        flex_contents=flex,
        alt_text=alt_text,
    )


# ---------------------------------------------------------------------------
# マイリスト (ウォッチリスト, PROPOSAL-0012)
# ---------------------------------------------------------------------------


def _emit_watchlist_event(action: str, *, user_id: str, ticker: str) -> None:
    """watchlist 操作を business_event として best-effort で記録する。

    instrumentation 未初期化 (テスト等) でも落とさない。
    """
    try:
        from instrumentation import get_analytics_logger  # noqa: PLC0415

        get_analytics_logger().emit(
            event_type="business_event",
            event_version="1.0.0",
            severity="INFO",
            fields={
                "business_domain": "stock_analysis",
                "action": action,
                "resource_type": "watchlist",
                "resource_id": ticker,
                "attributes": {},
            },
            user_id=user_id,
        )
    except Exception:
        logger.debug("watchlist analytics emit skipped", exc_info=True)


async def _cmd_watchlist_add(
    args: list[str], event: LineTextEvent, deps: HandlerDeps
) -> None:
    if not args:
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text="使い方: 追加 <銘柄名 or ティッカー>\n例: 追加 トヨタ / 追加 AAPL",
        )
        return

    user_id = event.line_user_id
    target = " ".join(args).strip()

    if await count_watchlist(user_id) >= config.settings.watchlist_max_items:
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text=(
                f"マイリストが上限 ({config.settings.watchlist_max_items}件) に達しています。"
                "「削除 <ティッカー>」で減らしてから追加してください。"
            ),
        )
        return

    # 銘柄解決ゲート (分析と同じ): 高確度なら確定、低確度は候補提示 (追加コマンド)。
    try:
        resolved = await resolve_ticker(target)
    except Exception:
        logger.exception("resolve_ticker failed for %s", target)
        resolved = None
    if resolved is None or resolved.source not in _CONFIDENT_SOURCES:
        candidates = search_candidates(target)
        if candidates:
            flex = ticker_candidates_bubble(
                query=target, candidates=candidates, command="追加"
            )
            fallback = (
                f"「{target}」の候補:\n"
                + "\n".join(f"・追加 {c.ticker} — {c.name or ''}" for c in candidates[:5])
                + "\n上のコマンドを送るとマイリストに追加します。"
            )
            await _reply_flex_or_text(
                deps,
                reply_token=event.reply_token,
                fallback_text=fallback,
                flex_contents=flex,
                alt_text=f"「{target}」の銘柄候補",
            )
        else:
            await deps.line_client.reply_text(
                reply_token=event.reply_token,
                text=ANALYZE_NOT_FOUND_TEMPLATE.format(target=target),
            )
        return

    ticker = resolved.ticker
    name = resolved.company_name
    if not name:
        # ティッカー直接/候補タップ等で名前が無い場合は補完 (ローカル→yfinance)
        try:
            name = await asyncio.to_thread(fetch_ticker_name, ticker)
        except Exception:
            logger.debug("fetch_ticker_name failed for %s", ticker, exc_info=True)
            name = None
    added = await add_watchlist_item(user_id, ticker, name)
    label = f"{name} ({ticker})" if name else ticker
    if added:
        _emit_watchlist_event("watchlist_added", user_id=user_id, ticker=ticker)
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text=f"✅ マイリストに追加しました: {label}\n「マイリスト」で一覧、「スクリーニング マイ」で分析できます。",
        )
    else:
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text=f"すでにマイリストにあります: {label}",
        )


async def _cmd_watchlist_remove(
    args: list[str], event: LineTextEvent, deps: HandlerDeps
) -> None:
    if not args:
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text="使い方: 削除 <ティッカー>\n例: 削除 7203.T / 削除 AAPL",
        )
        return

    user_id = event.line_user_id
    target = " ".join(args).strip()
    # 高確度に解決できればその ticker、できなければ入力をそのまま ticker とみなす。
    try:
        resolved = await resolve_ticker(target)
    except Exception:
        resolved = None
    ticker = (
        resolved.ticker
        if resolved is not None and resolved.source in _CONFIDENT_SOURCES
        else target.upper()
    )

    removed = await remove_watchlist_item(user_id, ticker)
    # 旧データ救済: 正規化後 ticker で一致しない場合は生入力でも試す。
    # 例: JPX 新形式コード対応前に「285A」(.T 無し) で登録された行は、
    # 対応後 resolve が「285A.T」を返すため正規化値では消せない。
    if not removed:
        raw = target.upper()
        if raw != ticker and await remove_watchlist_item(user_id, raw):
            removed = True
            ticker = raw
    if removed:
        _emit_watchlist_event("watchlist_removed", user_id=user_id, ticker=ticker)
        await deps.line_client.reply_text(
            reply_token=event.reply_token, text=f"🗑️ マイリストから削除しました: {ticker}"
        )
    else:
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text=f"マイリストに {target} が見つかりませんでした。「マイリスト」で一覧を確認できます。",
        )


async def _cmd_watchlist_show(event: LineTextEvent, deps: HandlerDeps) -> None:
    items = await get_watchlist(event.line_user_id)
    if not items:
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text=(
                "マイリストは空です。\n「追加 トヨタ」「追加 AAPL」のように銘柄を"
                "登録できます。"
            ),
        )
        return

    flex = watchlist_bubble(items=items)
    fallback = (
        "📋 マイリスト\n"
        + "\n".join(f"・{it.get('name') or it['ticker']} ({it['ticker']})" for it in items)
        + "\n\n「分析 <ティッカー>」「削除 <ティッカー>」「スクリーニング マイ」"
    )
    await _reply_flex_or_text(
        deps,
        reply_token=event.reply_token,
        fallback_text=fallback,
        flex_contents=flex,
        alt_text=f"マイリスト ({len(items)}件)",
    )


# ---------------------------------------------------------------------------
# /分析 (非同期: ack reply → background → push)
# ---------------------------------------------------------------------------


# この confidence/source なら曖昧さ無しとして分析に進む (regex=0.95 / dict=0.90)。
# yfinance 検索 (0.75) や LLM フォールバック (0.30) は誤銘柄リスクがあるため、
# 候補提示に切り替える (実機で「違う企業が分析された」報告への対応)。
_CONFIDENT_SOURCES = {"regex", "dict"}

ANALYZE_NOT_FOUND_TEMPLATE = (
    "🔍 「{target}」に該当する銘柄が見つかりませんでした。\n"
    "ティッカーで指定してみてください (例: 分析 7203.T / 分析 AAPL)。"
)


async def _cmd_analyze(
    args: list[str], event: LineTextEvent, deps: HandlerDeps
) -> None:
    if not args:
        await deps.line_client.reply_text(
            reply_token=event.reply_token,
            text="使い方: 分析 <銘柄名 or ティッカー>\n例: 分析 トヨタ / 分析 AAPL",
        )
        return

    user_id = event.line_user_id
    target = " ".join(args).strip()

    # 銘柄解決ゲート: 高確度 (regex/dict) でなければ分析せず候補を提示する。
    # 誤銘柄に Opus 分析が走るのを防ぐ。候補提示はレート制限を消費しない。
    try:
        resolved = await resolve_ticker(target)
    except Exception:
        logger.exception("resolve_ticker failed for %s (continuing as-is)", target)
        resolved = None
    if resolved is not None and resolved.source not in _CONFIDENT_SOURCES:
        candidates = search_candidates(target)
        if candidates:
            flex = ticker_candidates_bubble(query=target, candidates=candidates)
            fallback = (
                f"「{target}」の候補:\n"
                + "\n".join(
                    f"・分析 {c.ticker} — {c.name or ''}" for c in candidates[:5]
                )
                + "\n上のコマンドを送ると分析を開始します。"
            )
            await _reply_flex_or_text(
                deps,
                reply_token=event.reply_token,
                fallback_text=fallback,
                flex_contents=flex,
                alt_text=f"「{target}」の銘柄候補",
            )
        else:
            await deps.line_client.reply_text(
                reply_token=event.reply_token,
                text=ANALYZE_NOT_FOUND_TEMPLATE.format(target=target),
            )
        return

    # レート制限: 1 ユーザ 1 日の分析回数上限 (Opus コスト抑制、PROPOSAL-0011 §3.4)。
    if not get_analyze_limiter().check_and_increment(user_id):
        await deps.line_client.reply_text(
            reply_token=event.reply_token, text=ANALYZE_RATE_LIMITED_TEXT
        )
        return

    # ack reply (解決済の銘柄名があれば併記)
    ack_target = target
    if resolved is not None and resolved.company_name:
        ack_target = f"{resolved.company_name} ({resolved.ticker})"
    await deps.line_client.reply_text(
        reply_token=event.reply_token,
        text=ANALYZE_ACK_TEMPLATE.format(target=ack_target, eta=_analyze_eta()),
    )

    # P3-A: tasks_enabled なら Cloud Tasks に委譲 (worker run が実行)。
    # enqueue 失敗時や dev (tasks 無効) は従来の in-process 実行にフォールバック。
    if config.settings.tasks_enabled:
        try:
            enqueue_analysis(user_id, target)
            return
        except Exception:
            logger.exception("enqueue_analysis failed; falling back to in-process")

    async def _job() -> None:
        try:
            await run_and_deliver_analysis(deps, to=user_id, target=target)
        except Exception as e:
            await push_analysis_failure(
                deps, to=user_id, target=target, reason=str(e)
            )

    deps.schedule_background(_job)


async def run_and_deliver_analysis(
    deps: HandlerDeps, *, to: str, target: str
) -> None:
    """分析を実行して 3 点配信する。失敗時はエラーを push して例外を再送出する。

    in-process 実行 (webhook) と Cloud Tasks worker の両方から使う共通経路。
    worker は例外を捕捉してリトライ判定に使う。
    """
    runner = deps.analyze_runner or _default_analyze_runner
    try:
        result = await runner(AnalysisRequest(query=target, period="3mo"))
    except Exception:
        logger.exception("analyze failed for %s", target)
        raise
    await _deliver_analysis(deps, to=to, result=result)


async def push_analysis_failure(deps: HandlerDeps, *, to: str, target: str, reason: str) -> None:
    """分析失敗を LINE Push で通知する (リトライ尽きた worker / inline 失敗時)。"""
    try:
        await deps.line_client.push_text(
            to=to, text=ANALYZE_FAIL_TEMPLATE.format(target=target, reason=reason[:200])
        )
    except Exception:
        logger.exception("failed to push analysis failure notice")


# ---------------------------------------------------------------------------
# 分析結果の 3 点配信 (要約 Flex / チャート画像 / 全文 Markdown DL)
# ---------------------------------------------------------------------------


def _build_report_url(report_text: str) -> str | None:
    """全文 Markdown を media backend に保存し、DL 用 URL を返す (P3-A: memory|gcs)。"""
    return store_report_md(report_text)


def _build_image_url(chart_path: str | None) -> str | None:
    """チャート PNG を media backend に保存し、配信 URL を返す (P3-A: memory|gcs)。

    chart 不在 / 読込失敗 / backend 未設定なら None。
    """
    if not chart_path:
        return None
    try:
        with open(chart_path, "rb") as f:
            png = f.read()
    except OSError:
        logger.exception("failed to read chart file: %s", chart_path)
        return None
    return store_chart_png(png)


async def _deliver_analysis(
    deps: HandlerDeps, *, to: str, result: AnalyzeResult
) -> None:
    """(1) 要約 Flex (2) チャート画像 (3) 全文リンク (HTML 閲覧 + .md DL) を Push する。"""
    html_url = store_report_html(result.report_text)
    md_url = _build_report_url(result.report_text)
    image_url = _build_image_url(result.chart_path)

    label = result.company_name or result.ticker

    # (1) 要約 Flex (全文ボタン付き) + text フォールバック
    flex = analysis_summary_bubble(
        ticker=result.ticker,
        company_name=result.company_name,
        body_text=result.report_text,
        report_url=html_url,
        md_url=md_url,
        recommendation=result.recommendation,
    )
    fallback = f"{label} ({result.ticker}) 分析結果\n\n{result.report_text[:1500]}"
    if html_url:
        fallback += f"\n\n📖 全文: {html_url}"
    await _push_flex_or_text(
        deps,
        to=to,
        fallback_text=fallback,
        flex_contents=flex,
        alt_text=f"{label} 分析完了",
    )

    # (2) チャート画像 (任意)
    if image_url:
        try:
            await deps.line_client.push_image(
                to=to,
                original_content_url=image_url,
                preview_image_url=image_url,
            )
        except Exception:
            logger.exception("push_image failed (continuing)")


# ---------------------------------------------------------------------------
# 標準 analyze runner (orchestrator の SSE ストリームを集約してテキスト化)
# ---------------------------------------------------------------------------


async def _default_analyze_runner(req: AnalysisRequest) -> AnalyzeResult:
    """run_analysis のイベントストリームから本文・銘柄情報・チャートパスを集約する。"""
    parts: list[str] = []
    ticker = req.query
    company_name: str | None = None
    chart_path: str | None = None
    recommendation: dict | None = None
    async for event in run_analysis(req):
        et = event.get("type") if isinstance(event, dict) else None
        if et == "report_complete":
            ticker = event.get("ticker", ticker)
            company_name = event.get("company_name") or company_name
            report = event.get("report") or {}
            chart_path = report.get("chart_path") or chart_path
            recommendation = report.get("recommendation") or recommendation
            text = report.get("report_text") or ""
            if text:
                parts.append(text)
        elif et == "AssistantMessage":
            # 既に "report_complete" で本文を集めるため、ここでは無視
            pass
    body = "\n".join(parts).strip() or "(分析本文が空でした。再度お試しください)"
    return AnalyzeResult(
        ticker=ticker,
        company_name=company_name,
        report_text=body,
        chart_path=chart_path,
        recommendation=recommendation,
    )


# ---------------------------------------------------------------------------
# FastAPI BackgroundTasks 互換のシンプルなスケジューラ
# ---------------------------------------------------------------------------


def schedule_via_create_task(coro_factory: Callable[[], Awaitable[None]]) -> None:
    """asyncio.create_task で fire-and-forget。FastAPI BackgroundTasks 不在時のフォールバック。"""
    asyncio.create_task(coro_factory())
