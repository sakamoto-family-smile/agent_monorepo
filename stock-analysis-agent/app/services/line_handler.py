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
from config import settings
from models.stock import (
    AnalysisRequest,
    FundRecommendRequest,
    ScreenerRequest,
)
from services.access_control import get_analyze_limiter, is_user_allowed
from services.blob_store import get_image_store, get_report_store
from services.line_client import (
    LineBotClient,
    LineEvent,
    LineTextEvent,
)
from services.line_flex import (
    analysis_summary_bubble,
    funds_ranking_carousel,
    screener_ranking_carousel,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# コマンド文面
# ---------------------------------------------------------------------------

HELP_TEXT = (
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
    "■ 個別株分析 (分析開始から完了まで 30秒〜2分)\n"
    "  ・分析 トヨタ\n"
    "  ・分析 AAPL\n"
    "  ・分析 7203.T\n\n"
    "※ 投資判断はご自身の責任でお願いします。"
)

UNKNOWN_HINT = "認識できない入力でした。「ヘルプ」と送るとコマンド一覧を表示します。"

DISCLAIMER_SHORT = (
    "※ 情報提供のみを目的としており、投資勧誘・個別の助言ではありません。"
)

ANALYZE_ACK_TEMPLATE = (
    "📊 {target} の分析を開始しました。\n"
    "完了まで 30秒〜2分ほどかかります。完了次第、結果をお送りします。"
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
    """

    ticker: str
    company_name: str | None
    report_text: str
    chart_path: str | None = None


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
}


# ---------------------------------------------------------------------------
# テキストイベント
# ---------------------------------------------------------------------------


async def _handle_text(event: LineTextEvent, deps: HandlerDeps) -> None:
    # allow-list: FAMILY_USER_IDS 設定時は家族以外を無視 (返信せず黙殺)。
    # public webhook + Claude Opus 課金の濫用を防ぐ (PROPOSAL-0011 §3.4)。
    if not is_user_allowed(event.line_user_id):
        logger.info("ignoring message from non-allowlisted user")
        return

    cmd, args = _normalize_command(event.text)
    if not cmd:
        await deps.line_client.reply_text(reply_token=event.reply_token, text=UNKNOWN_HINT)
        return

    cmd_lower = cmd.lower()

    if cmd in _HELP_TOKENS or cmd_lower in _HELP_TOKENS:
        await deps.line_client.reply_text(reply_token=event.reply_token, text=HELP_TEXT)
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

    req = ScreenerRequest(market=market, top_n=10)
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
# /分析 (非同期: ack reply → background → push)
# ---------------------------------------------------------------------------


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

    # レート制限: 1 ユーザ 1 日の分析回数上限 (Opus コスト抑制、PROPOSAL-0011 §3.4)。
    if not get_analyze_limiter().check_and_increment(user_id):
        await deps.line_client.reply_text(
            reply_token=event.reply_token, text=ANALYZE_RATE_LIMITED_TEXT
        )
        return

    target = " ".join(args).strip()
    # ack reply
    await deps.line_client.reply_text(
        reply_token=event.reply_token,
        text=ANALYZE_ACK_TEMPLATE.format(target=target),
    )

    # バックグラウンド実行
    runner = deps.analyze_runner or _default_analyze_runner

    async def _job() -> None:
        try:
            result = await runner(AnalysisRequest(query=target, period="3mo"))
        except Exception as e:
            logger.exception("background analyze failed for %s", target)
            await deps.line_client.push_text(
                to=user_id,
                text=ANALYZE_FAIL_TEMPLATE.format(target=target, reason=str(e)[:200]),
            )
            return

        await _deliver_analysis(deps, to=user_id, result=result)

    deps.schedule_background(_job)


# ---------------------------------------------------------------------------
# 分析結果の 3 点配信 (要約 Flex / チャート画像 / 全文 Markdown DL)
# ---------------------------------------------------------------------------


def _build_report_url(report_text: str) -> str | None:
    """全文 Markdown を ReportStore に入れ、DL 用 URL を返す。

    `public_base_url` 未設定 / 本文空なら None (URL 無しで Flex 要約のみ配信)。
    """
    base = settings.public_base_url
    if not base or not report_text:
        return None
    report_id = get_report_store().put(report_text.encode("utf-8"), "text/markdown")
    return f"{base}/api/line/report/{report_id}.md"


def _build_image_url(chart_path: str | None) -> str | None:
    """チャート PNG を ImageStore に入れ、配信 URL を返す。

    `public_base_url` 未設定 / chart 不在 / 読込失敗なら None。
    """
    base = settings.public_base_url
    if not base or not chart_path:
        return None
    try:
        with open(chart_path, "rb") as f:
            png = f.read()
    except OSError:
        logger.exception("failed to read chart file: %s", chart_path)
        return None
    image_id = get_image_store().put(png, "image/png")
    return f"{base}/api/line/image/{image_id}.png"


async def _deliver_analysis(
    deps: HandlerDeps, *, to: str, result: AnalyzeResult
) -> None:
    """(1) 要約 Flex (2) チャート画像 (3) 全文 DL リンク を Push する。"""
    report_url = _build_report_url(result.report_text)
    image_url = _build_image_url(result.chart_path)

    label = result.company_name or result.ticker

    # (1) 要約 Flex (全文ボタン付き) + text フォールバック
    flex = analysis_summary_bubble(
        ticker=result.ticker,
        company_name=result.company_name,
        body_text=result.report_text,
        report_url=report_url,
    )
    fallback = f"{label} ({result.ticker}) 分析結果\n\n{result.report_text[:1500]}"
    if report_url:
        fallback += f"\n\n📄 全文(.md): {report_url}"
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
    async for event in run_analysis(req):
        et = event.get("type") if isinstance(event, dict) else None
        if et == "report_complete":
            ticker = event.get("ticker", ticker)
            company_name = event.get("company_name") or company_name
            report = event.get("report") or {}
            chart_path = report.get("chart_path") or chart_path
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
    )


# ---------------------------------------------------------------------------
# FastAPI BackgroundTasks 互換のシンプルなスケジューラ
# ---------------------------------------------------------------------------


def schedule_via_create_task(coro_factory: Callable[[], Awaitable[None]]) -> None:
    """asyncio.create_task で fire-and-forget。FastAPI BackgroundTasks 不在時のフォールバック。"""
    asyncio.create_task(coro_factory())
