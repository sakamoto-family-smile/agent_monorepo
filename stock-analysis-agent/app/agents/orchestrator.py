import asyncio
import hashlib
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime
from typing import AsyncIterator, Optional

from claude_agent_sdk import query, ClaudeAgentOptions

from analytics_platform.observability.hashing import sha256_prefixed
from models.stock import (
    BUY_RECOMMENDATION_DISCLAIMER,
    AnalysisRequest,
    AnalysisReport,
    BuyRecommendation,
    SentimentData,
)
from agents.ticker_resolver import resolve_ticker
from agents.data_collection import fetch_ohlcv, fetch_fundamentals
from agents.technical_analysis import compute_indicators
from agents.chart_generator import generate_chart
from agents.forecast import MonteCarloForecaster, ForecastResult
from agents.edinet_collector import EdinetFilingResult, collect_filings
from instrumentation import get_analytics_logger, get_content_router, get_tracer
from services.database import save_report
from config import settings

logger = logging.getLogger(__name__)

# Claude Agent SDK の `query()` 1 メッセージあたりの待機 timeout (秒)。
#
# EDINET 統合 (proposal 0006 Phase 1d+) が入る前は yfinance + Brave Search のみで
# 30 秒以内に応答していたため 120 秒で十分だったが、 Phase 1d 以降の経路では
# Claude が PDF を Read tool で複数ページ読みつつ最終レポートをまとめるため、
# **個別メッセージ間で 100 秒級の沈黙が現実的に発生する** (diag3 で 108 秒の gap
# を観測)。 default を 300 秒 (5 分) に引き上げ、 env で override 可能のままにする。
_INTER_MESSAGE_TIMEOUT = int(os.getenv("AGENT_MESSAGE_TIMEOUT_SECONDS", "300"))


_FORECAST_DISCLAIMER = (
    "この予測は過去の値動きから推計したモンテカルロ・シミュレーション（統計的試算）であり、"
    "将来の株価を保証するものでも投資助言でもありません。投資判断は自己責任で行ってください。"
)


def _format_forecast_summary(forecast: "ForecastResult | None") -> str:
    """Render the simulated percentile bands as factual text for the LLM.

    These numbers come from the simulation; the prompt instructs the model to use
    them verbatim and never fabricate price targets.
    """
    if forecast is None or not forecast.bands:
        return ""
    bands = forecast.bands
    end = forecast.dates[-1] if forecast.dates else ""
    lines = [
        f"予測期間: 翌営業日〜{forecast.horizon_days}営業日先（最終日: {end}）",
        f"起点価格（現在値）: {forecast.last_price:.2f}",
        f"{forecast.horizon_days}営業日先の予測レンジ:",
    ]
    for p in sorted(bands.keys()):
        lines.append(f"  P{p}: {bands[p][-1]:.2f}")
    lines.append(f"（注）{_FORECAST_DISCLAIMER}")
    return "\n".join(lines)


def _build_analysis_prompt(
    ticker: str,
    company_name: Optional[str],
    ohlcv_summary: str,
    technical_summary: str,
    fundamental_summary: str,
    edinet_section: str = "",
    forecast_summary: str = "",
) -> str:
    name = company_name or ticker
    forecast_block = (
        f"\n\n## 価格予測（モンテカルロ統計シミュレーション）\n{forecast_summary}"
        if forecast_summary
        else ""
    )
    # Number this instruction after the (optional) EDINET item: 6 normally, 7 if EDINET present.
    forecast_item_no = 7 if edinet_section else 6
    forecast_instr = (
        f"\n{forecast_item_no}. **価格予測の解説**: 上記「価格予測」のパーセンタイル値（P10〜P90）を"
        "**この prompt に記載された数値のみ**を用いて解説してください。"
        "新たな価格目標を自分で計算・創作してはいけません。"
        f"解説の最後に必ず次の免責文を含めてください: 「{_FORECAST_DISCLAIMER}」"
        if forecast_summary
        else ""
    )
    # 投資判断 (購入推奨) は常に最後の指示項目。EDINET / 予測の有無で項番がずれる。
    reco_item_no = 6 + (1 if edinet_section else 0) + (1 if forecast_summary else 0)
    reco_instr = f"""
{reco_item_no}. **投資判断**: 上記の分析を総合し、現時点で購入を検討できる状況かを判定してください。レポートの末尾に必ず次の書式のセクションを出力してください（見出しと「判定:」の書式を変えないこと）:

## 投資判断
判定: 「買い検討」「様子見」「見送り」のいずれか 1 つ
根拠:
- （箇条書き 2〜4 点。テクニカル / ファンダメンタル / センチメントそれぞれの寄与を明示）
反対シナリオ:
- （判定が外れるとしたらどのような場合か 1〜2 点）

「必ず買うべき」等の断定的な表現は避け、セクション末尾に必ず次の免責文をそのまま含めてください: 「{BUY_RECOMMENDATION_DISCLAIMER}」"""
    edinet_block = f"\n\n## EDINET 法定開示\n{edinet_section}" if edinet_section else ""
    edinet_instr = (
        "\n6. **EDINET 法定開示の活用**: 上記の有価証券報告書 / 四半期報告書を活用してください。 "
        "**主要財務数値 (XBRL 抽出) は本 prompt に表として含まれている**ので、 YoY や "
        "セグメント比較は表の数値を直接使い、 定性情報 (中期経営計画 / 事業等のリスク等) は "
        "PDF を Read tool で開いて引用してください"
        if edinet_section
        else ""
    )
    return f"""あなたは株式アナリストです。以下のデータを元に、{name}（{ticker}）の詳細な投資分析レポートを日本語で作成してください。

## 価格データ（直近）
{ohlcv_summary}

## テクニカル指標
{technical_summary}

## ファンダメンタルズ
{fundamental_summary}{edinet_block}{forecast_block}

## 分析指示
1. **テクニカル分析**: トレンド、サポート/レジスタンス、オシレーター（RSI, MACD）、ボリンジャーバンドの状態を分析してください
2. **ファンダメンタル分析**: バリュエーション（PER, PBR）、収益性、財務健全性を評価してください
3. **センチメント分析**: Brave Searchを使って最新ニュースを検索し、市場センチメントを分析してください（キーワード: "{name} 株価 ニュース"）
4. **総合評価**: 強気/中立/弱気の判断と、その根拠を明確に示してください
5. **リスク要因**: 主要なダウンサイドリスクを列挙してください{edinet_instr}{forecast_instr}{reco_instr}

レポートは投資家が意思決定に使えるよう、具体的かつ客観的に記述してください。"""


# ---------------------------------------------------------------------------
# 投資判断セクションのパース (report_text → BuyRecommendation)
# ---------------------------------------------------------------------------

_RATING_BY_LABEL = {
    "買い検討": "buy_candidate",
    "様子見": "hold",
    "見送り": "avoid",
}

_RECO_SECTION_RE = re.compile(
    r"^##\s*投資判断\s*$(?P<body>.*?)(?=^##\s|\Z)", re.MULTILINE | re.DOTALL
)
_VERDICT_RE = re.compile(r"^判定[:：]\s*(?P<verdict>.+)$", re.MULTILINE)
_BULLET_RE = re.compile(r"^[\-\*・•]\s*(?P<item>.+)$")


def _parse_buy_recommendation(report_text: str) -> BuyRecommendation | None:
    """レポート末尾の「## 投資判断」セクションを構造化する。

    LLM 出力が指示書式から外れていた場合は None を返し、自由テキストのみの
    従来動作にフォールバックする (分析全体は落とさない)。

    判定ラベルは **完全一致** のみ受理する (括弧書きの注釈は除去)。
    「見送りに近い様子見」のようなヘッジ表現を部分一致で拾うと本文と逆の
    バッジを自信ありげに表示してしまうため、曖昧なら fail-closed で None。
    """
    if not isinstance(report_text, str) or not report_text:
        return None
    section_match = _RECO_SECTION_RE.search(report_text)
    if not section_match:
        return None
    section = section_match.group("body")

    verdict_match = _VERDICT_RE.search(section)
    if not verdict_match:
        return None
    verdict = verdict_match.group("verdict").strip().strip("「」*")
    # 「様子見（買い材料不足）」のような括弧注釈のみ許容し、残りは完全一致を要求
    label = re.split(r"[（(]", verdict, maxsplit=1)[0].strip().strip("「」*")
    if label not in _RATING_BY_LABEL:
        return None

    reasons: list[str] = []
    in_reasons = False
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("根拠"):
            in_reasons = True
            continue
        if stripped.startswith("反対シナリオ"):
            break
        if in_reasons:
            bullet = _BULLET_RE.match(stripped)
            if bullet:
                reasons.append(bullet.group("item").strip())

    return BuyRecommendation(
        rating=_RATING_BY_LABEL[label], label=label, reasons=reasons
    )


def _format_ohlcv_summary(ohlcv) -> str:
    if not ohlcv:
        return "データなし"
    latest = ohlcv[-1]
    oldest = ohlcv[0]
    change = ((latest.close - oldest.close) / oldest.close * 100) if oldest.close else 0
    return (
        f"期間: {oldest.date} ～ {latest.date}\n"
        f"現在値: {latest.close:.2f}\n"
        f"始値(期間初): {oldest.open:.2f}\n"
        f"期間高値: {max(r.high for r in ohlcv):.2f}\n"
        f"期間安値: {min(r.low for r in ohlcv):.2f}\n"
        f"期間騰落率: {change:+.2f}%"
    )


def _format_technical_summary(tech) -> str:
    if not tech:
        return "データなし"
    lines = []
    if tech.sma_20: lines.append(f"SMA20: {tech.sma_20:.2f}")
    if tech.sma_50: lines.append(f"SMA50: {tech.sma_50:.2f}")
    if tech.ema_20: lines.append(f"EMA20: {tech.ema_20:.2f}")
    if tech.rsi_14: lines.append(f"RSI(14): {tech.rsi_14:.2f}")
    if tech.macd: lines.append(f"MACD: {tech.macd:.4f}")
    if tech.macd_signal: lines.append(f"MACDシグナル: {tech.macd_signal:.4f}")
    if tech.bb_upper: lines.append(f"BB上限: {tech.bb_upper:.2f}")
    if tech.bb_lower: lines.append(f"BB下限: {tech.bb_lower:.2f}")
    return "\n".join(lines) or "データなし"


def _format_fundamental_summary(fund) -> str:
    if not fund:
        return "データなし"
    lines = []
    if fund.pe_ratio: lines.append(f"PER: {fund.pe_ratio:.2f}倍")
    if fund.pb_ratio: lines.append(f"PBR: {fund.pb_ratio:.2f}倍")
    if fund.market_cap: lines.append(f"時価総額: {fund.market_cap/1e8:.0f}億")
    if fund.dividend_yield: lines.append(f"配当利回り: {fund.dividend_yield*100:.2f}%")
    if fund.eps: lines.append(f"EPS: {fund.eps:.2f}")
    if fund.roe: lines.append(f"ROE: {fund.roe*100:.2f}%")
    if fund.sector: lines.append(f"セクター: {fund.sector}")
    if fund.industry: lines.append(f"業種: {fund.industry}")
    return "\n".join(lines) or "データなし"


def _materialize_edinet_filings(
    filings: list[EdinetFilingResult], workspace_dir: str
) -> str:
    """EDINET 書類 PDF を workspace に書き出して prompt に組み込む文字列を返す。

    Phase 2b 以降は XBRL から抽出した Tier 1+2 構造化数値も markdown 表として
    prompt に直接埋め込み、 Claude の数値計算 (YoY / セグメント比較等) を支援する。

    Claude Agent SDK には Read tool を渡しているため、 prompt に「この PDF を Read
    で開いて分析せよ」 と指示すれば Claude が自発的に読みに行く。
    """
    edinet_dir = os.path.join(workspace_dir, "edinet")
    os.makedirs(edinet_dir, exist_ok=True)

    lines: list[str] = [
        "以下の法定開示書類を分析に活用してください。",
        "各 PDF (定性情報用) は数十〜数百ページのため、 Read tool で目次から "
        "関連セクション (セグメント別売上 / 中期経営計画 / 事業等のリスク 等) を抽出。",
        "**主要財務数値 (XBRL 抽出)** は本 prompt に直接掲載してあるので、 そのまま "
        "計算 (YoY / セグメント比較等) に利用してください。",
        "",
    ]

    # 書類リスト + financials
    for filing in filings:
        path = os.path.join(edinet_dir, f"{filing.metadata.document_id}.pdf")
        try:
            with open(path, "wb") as f:
                f.write(filing.body.bytes_payload)
        except OSError:
            logger.exception(
                "failed to write EDINET PDF document_id=%s",
                filing.metadata.document_id,
            )
            continue
        m = filing.metadata
        type_label = _document_type_label(str(m.document_type))
        lines.append(
            f"- 📄 `{path}` — **{type_label}** ({m.submit_date}、 "
            f"期末: {m.period_end or '—'}、 {m.description})"
        )

    financials_section = _format_xbrl_financials_section(filings)
    if financials_section:
        lines.append("")
        lines.append(financials_section)

    return "\n".join(lines)


def _format_xbrl_financials_section(filings: list[EdinetFilingResult]) -> str:
    """XBRL Tier 1 + Tier 2 数値を markdown 表として整形する。

    全件 financials=None なら空文字を返す (Claude prompt に section を追加しない)。
    """
    enriched = [f for f in filings if f.financials is not None]
    if not enriched:
        return ""

    out: list[str] = ["### 主要財務数値 (XBRL 抽出、 連結ベース、 円単位)"]

    # Tier 1: 期末順 (古い順) の表
    out.append("")
    out.append("#### Tier 1: 連結 P/L / BS 主要項目")
    out.append("")
    out.append("| 期末 | 種別 | 売上 | 営業利益 | 経常利益 | 純利益 | 総資産 | 純資産 |")
    out.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for f in enriched:
        fin = f.financials
        assert fin is not None
        type_label = _document_type_label(str(f.metadata.document_type))
        out.append(
            f"| {fin.fiscal_year_end or f.metadata.period_end or '—'} "
            f"| {type_label} "
            f"| {_fmt_amount(fin.net_sales)} "
            f"| {_fmt_amount(fin.operating_profit)} "
            f"| {_fmt_amount(fin.ordinary_profit)} "
            f"| {_fmt_amount(fin.net_profit)} "
            f"| {_fmt_amount(fin.total_assets)} "
            f"| {_fmt_amount(fin.net_assets)} |"
        )

    # Tier 2: セグメント情報 (最新の有報 1 件分のみ)
    annual_with_segments = next(
        (
            f
            for f in reversed(enriched)
            if f.financials and f.financials.segments
        ),
        None,
    )
    if annual_with_segments and annual_with_segments.financials:
        out.append("")
        out.append(
            f"#### Tier 2: セグメント別売上 / 営業利益 "
            f"(期末 {annual_with_segments.financials.fiscal_year_end or '—'})"
        )
        out.append("")
        out.append("| セグメント | 売上 | 営業利益 |")
        out.append("|---|---:|---:|")
        for seg in annual_with_segments.financials.segments:
            out.append(
                f"| {seg.segment_name} "
                f"| {_fmt_amount(seg.net_sales)} "
                f"| {_fmt_amount(seg.operating_profit)} |"
            )

    return "\n".join(out)


def _fmt_amount(value: float | None) -> str:
    """円単位 float を 「1,234 億円」 等の表記にする。 None は 「—」。"""
    if value is None:
        return "—"
    abs_val = abs(value)
    if abs_val >= 1e12:
        return f"{value / 1e12:,.2f} 兆円"
    if abs_val >= 1e8:
        return f"{value / 1e8:,.0f} 億円"
    if abs_val >= 1e6:
        return f"{value / 1e6:,.0f} 百万円"
    return f"{value:,.0f} 円"


def _document_type_label(doc_type_code: str) -> str:
    mapping = {
        "120": "有価証券報告書",
        "140": "四半期報告書",
        "160": "半期報告書",
        "180": "臨時報告書",
        "130": "訂正届出書",
        "350": "大量保有報告書",
        "360": "変更報告書",
        "490": "公開買付届出書",
    }
    return mapping.get(doc_type_code, f"書類 (code={doc_type_code})")


def _write_mcp_config(workspace_dir: str, proxy_url: str) -> None:
    """Write MCP config for brave-search through proxy."""
    config = {
        "mcpServers": {
            "brave-search": {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-brave-search"],
                "env": {
                    "BRAVE_API_KEY": os.getenv("BRAVE_API_KEY", ""),
                },
            }
        }
    }
    if proxy_url:
        config = {
            "mcpServers": {
                "brave-search": {
                    "transport": "http",
                    "url": proxy_url,
                }
            }
        }
    mcp_config_path = os.path.join(workspace_dir, ".mcp.json")
    with open(mcp_config_path, "w") as f:
        json.dump(config, f, indent=2)
    logger.debug("MCP config written to %s", mcp_config_path)


async def run_analysis(request: AnalysisRequest) -> AsyncIterator[dict]:
    """Run full stock analysis pipeline.

    Observability: 各ステップで span を作り、`tool_invocation` / `llm_call` /
    `business_event` / `error_event` / `conversation_event` を emit する。
    """
    al = get_analytics_logger()
    cr = get_content_router()
    tracer = get_tracer()

    session_id = f"analysis_{uuid.uuid4().hex[:16]}"
    query_hash = sha256_prefixed(request.query)

    with tracer.start_as_current_span("agent.run_analysis") as root_span:
        root_span.set_attribute("session.id", session_id)
        root_span.set_attribute("input.query_hash", query_hash)

        # 開始イベント
        al.emit(
            event_type="conversation_event",
            event_version="1.0.0",
            severity="INFO",
            fields={
                "conversation_phase": "started",
                "agent_id": settings.analytics_service_name,
                "initial_query_hash": query_hash,
            },
            session_id=session_id,
        )

        try:
            async for event in _run_analysis_inner(
                request, session_id=session_id, al=al, cr=cr, tracer=tracer
            ):
                yield event
        except Exception as exc:
            al.emit(
                event_type="error_event",
                event_version="1.0.0",
                severity="ERROR",
                fields={
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:1000],
                    "error_category": "internal",
                    "is_retriable": False,
                },
                session_id=session_id,
            )
            al.emit(
                event_type="conversation_event",
                event_version="1.0.0",
                severity="WARN",
                fields={
                    "conversation_phase": "aborted",
                    "agent_id": settings.analytics_service_name,
                    "initial_query_hash": query_hash,
                },
                session_id=session_id,
            )
            await al.flush()
            raise
        else:
            al.emit(
                event_type="conversation_event",
                event_version="1.0.0",
                severity="INFO",
                fields={
                    "conversation_phase": "ended",
                    "agent_id": settings.analytics_service_name,
                    "initial_query_hash": query_hash,
                },
                session_id=session_id,
            )
        finally:
            try:
                await al.flush()
            except Exception:
                logger.exception("analytics flush failed (non-fatal)")


def _build_forecast(ticker: str, ohlcv) -> ForecastResult | None:
    """Best-effort Monte Carlo forecast. Returns None on any failure (skip overlay).

    Kept behind the swappable Forecaster abstraction so the model can be replaced
    without touching the chart or delivery layers.
    """
    try:
        forecaster = MonteCarloForecaster(
            n_paths=settings.forecast_n_paths,
            seed=settings.forecast_seed,
        )
        return forecaster.forecast(ohlcv, horizon_days=settings.forecast_horizon_days)
    except Exception:  # noqa: BLE001 — 予測失敗で分析全体を落とさない
        logger.exception("Forecast generation failed for %s (continuing without it)", ticker)
        return None


async def _run_analysis_inner(
    request: AnalysisRequest,
    *,
    session_id: str,
    al,
    cr,
    tracer,
) -> AsyncIterator[dict]:
    """run_analysis の本体 (旧実装そのまま + 計装ポイント)。"""
    # Step 1: Resolve ticker
    resolve_result = await resolve_ticker(request.query)
    ticker = resolve_result.ticker
    company_name = resolve_result.company_name or request.query

    logger.info(
        "Resolved '%s' -> %s (confidence=%.2f, source=%s)",
        request.query, ticker, resolve_result.confidence, resolve_result.source
    )

    al.emit(
        event_type="business_event",
        event_version="1.0.0",
        severity="INFO",
        fields={
            "business_domain": "stock_analysis",
            "action": "ticker_resolved",
            "resource_type": "ticker",
            "resource_id": ticker,
            "attributes": {
                "company_name": company_name,
                "confidence": resolve_result.confidence,
                "source": resolve_result.source,
            },
        },
        session_id=session_id,
    )

    # Step 2: Fetch data in parallel
    async def _none() -> None:
        return None

    ohlcv, fundamentals = await asyncio.gather(
        fetch_ohlcv(ticker, request.period),
        fetch_fundamentals(ticker) if "fundamental" in request.analysis_types else _none(),
    )

    # Step 3: Technical analysis
    technical = None
    if "technical" in request.analysis_types:
        technical = compute_indicators(ohlcv)

    # Step 4: Generate chart (optionally with a Monte Carlo forecast fan overlay).
    # 予測は統計シミュレーションであり投資助言ではない。失敗しても分析全体は止めない。
    forecast = _build_forecast(ticker, ohlcv) if settings.forecast_enabled else None
    chart_path = generate_chart(ticker, ohlcv, settings.charts_dir, forecast=forecast)

    # Step 5: Build report data
    report = AnalysisReport(
        ticker=ticker,
        company_name=company_name,
        generated_at=datetime.now(),
        ohlcv=ohlcv,
        technical=technical,
        fundamental=fundamentals,
        chart_path=chart_path,
    )

    # Step 6: LLM analysis via Claude Agent SDK
    workspace_dir = os.path.join(settings.data_dir, "workspace")
    os.makedirs(workspace_dir, exist_ok=True)
    _write_mcp_config(workspace_dir, settings.mcp_proxy_url)

    # Step 6.5: EDINET 法定開示書類を取得 (proposal 0006 Phase 1d)。
    # EDINET_ENABLED=false / 未上場 / 米国株 等の場合は空 list 返却で skip。
    edinet_section = ""
    try:
        filings = await collect_filings(ticker)
    except Exception:  # noqa: BLE001 — EDINET 経路の失敗で全体を落とさない
        logger.exception("EDINET collection failed (continuing without EDINET data)")
        filings = []
    if filings:
        edinet_section = _materialize_edinet_filings(filings, workspace_dir)

    prompt = _build_analysis_prompt(
        ticker=ticker,
        company_name=company_name,
        ohlcv_summary=_format_ohlcv_summary(ohlcv),
        technical_summary=_format_technical_summary(technical),
        fundamental_summary=_format_fundamental_summary(fundamentals),
        edinet_section=edinet_section,
        forecast_summary=_format_forecast_summary(forecast),
    )

    options = ClaudeAgentOptions(
        model="claude-opus-4-6",
        permission_mode="bypassPermissions",
        cwd=workspace_dir,
        system_prompt="あなたは日本の株式市場に精通したプロのアナリストです。データに基づいた客観的な分析を行い、日本語でレポートを作成してください。",
        env={
            # claude_agent_sdk は HOME を必要とする。docker / Cloud Run でも
            # /tmp は書込可能なため恒常的にここを使う。本物のシークレット保存先
            # ではないので bandit B108 を抑止する。
            "HOME": "/tmp",  # nosec B108
            "ANTHROPIC_API_KEY": "",
            "CLAUDE_CODE_OAUTH_TOKEN": os.getenv("CLAUDE_CODE_OAUTH_TOKEN", ""),
            "BRAVE_API_KEY": os.getenv("BRAVE_API_KEY", ""),
        },
        allowed_tools=[
            "Read", "Glob", "Grep",
            "mcp__brave-search__*",
        ],
    )

    _sentinel = object()
    queue: asyncio.Queue = asyncio.Queue()
    report_text_parts = []
    pending_tool_starts: dict[str, float] = {}  # tool_use_id -> start ts (sec)
    pending_tool_names: dict[str, str] = {}     # tool_use_id -> tool name
    message_index = 0

    async def _producer() -> None:
        try:
            async for msg in query(prompt=prompt, options=options):
                await queue.put(msg)
        except Exception as exc:
            logger.exception("orchestrator producer error: %s", exc)
            await queue.put(exc)
        finally:
            await queue.put(_sentinel)

    with tracer.start_as_current_span("agent.claude_query") as llm_span:
        llm_span.set_attribute("session.id", session_id)
        task = asyncio.create_task(_producer())

        try:
            while True:
                try:
                    item = await asyncio.wait_for(
                        queue.get(), timeout=_INTER_MESSAGE_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    task.cancel()
                    raise TimeoutError(
                        f"エージェントが{_INTER_MESSAGE_TIMEOUT}秒以上応答しませんでした。"
                    )

                if item is _sentinel:
                    break
                if isinstance(item, Exception):
                    raise item

                # 計装: メッセージを観測
                message_index = _emit_sdk_message_events(
                    item,
                    al=al,
                    cr=cr,
                    session_id=session_id,
                    pending_tool_starts=pending_tool_starts,
                    pending_tool_names=pending_tool_names,
                    message_index=message_index,
                )

                # 既存処理: 本文収集
                msg_type = getattr(item, 'type', None) or item.__class__.__name__
                if hasattr(item, 'content'):
                    for block in (item.content or []):
                        if hasattr(block, 'text'):
                            report_text_parts.append(block.text)

                yield {"type": msg_type, "data": str(item)}

                # Claude Agent SDK の `ResultMessage` は **query の最終メッセージ**。
                # 通常はその後 `async for msg in query()` の iterator が即終了して
                # 生産者が sentinel を投入するが、 EDINET 経由の大型 prompt + 複数
                # PDF read の context では SDK 側の subprocess cleanup が遅延し、
                # iterator が closed されず生産者の `query()` が block する事例が
                # 観測された (1 件目 285A.T は正常完了、 2 件目 9616.T 開始時に
                # 顕在化)。 ResultMessage を消費した時点で生産者を撤収させて
                # consumer 側の timeout を回避する。
                if msg_type == "ResultMessage":
                    task.cancel()
                    break

        finally:
            if not task.done():
                task.cancel()
            import contextlib
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    # Save report
    report.report_text = "\n".join(report_text_parts)
    report.recommendation = _parse_buy_recommendation(report.report_text)
    report_id = await save_report(
        ticker=ticker,
        company_name=company_name,
        report_data=report.model_dump(mode="json"),
    )

    al.emit(
        event_type="business_event",
        event_version="1.0.0",
        severity="INFO",
        fields={
            "business_domain": "stock_analysis",
            "action": "report_saved",
            "resource_type": "report",
            "resource_id": str(report_id),
            "attributes": {
                "ticker": ticker,
                "company_name": company_name,
                "report_text_chars": len(report.report_text or ""),
                "recommendation_rating": (
                    report.recommendation.rating if report.recommendation else None
                ),
            },
        },
        session_id=session_id,
    )

    yield {
        "type": "report_complete",
        "report_id": report_id,
        "ticker": ticker,
        "company_name": company_name,
        "report": report.model_dump(mode="json"),
    }


# ---------------------------------------------------------------------------
# Claude Agent SDK メッセージ → analytics-platform イベント変換
# ---------------------------------------------------------------------------


def _emit_sdk_message_events(
    item,
    *,
    al,
    cr,
    session_id: str,
    pending_tool_starts: dict[str, float],
    pending_tool_names: dict[str, str],
    message_index: int,
) -> int:
    """SDK メッセージから llm_call / tool_invocation / message を emit。

    戻り値: 更新された message_index。
    """
    cls_name = item.__class__.__name__

    # AssistantMessage: 本文 / ツール呼出 / usage
    if cls_name == "AssistantMessage":
        usage = getattr(item, "usage", None) or {}
        model = getattr(item, "model", "unknown") or "unknown"
        stop_reason = getattr(item, "stop_reason", None)
        # llm_call event (usage が無いと token=0 で記録)
        try:
            al.emit(
                event_type="llm_call",
                event_version="1.0.0",
                severity="INFO",
                fields={
                    "llm_provider": "anthropic",
                    "llm_model": model,
                    "input_tokens": int(usage.get("input_tokens", 0) or 0),
                    "output_tokens": int(usage.get("output_tokens", 0) or 0),
                    "cache_read_tokens": int(
                        usage.get("cache_read_input_tokens", 0) or 0
                    ),
                    "cache_creation_tokens": int(
                        usage.get("cache_creation_input_tokens", 0) or 0
                    ),
                    "stop_reason": stop_reason,
                },
                session_id=session_id,
            )
        except Exception:
            logger.exception("failed to emit llm_call event")

        for block in getattr(item, "content", None) or []:
            block_cls = block.__class__.__name__
            if block_cls == "TextBlock":
                text = getattr(block, "text", "") or ""
                if not text:
                    continue
                msg_id = f"msg_{session_id}_{message_index}"
                stored = cr.route(
                    service_name=settings.analytics_service_name,
                    event_id=msg_id,
                    content=text,
                    mime_type="text/markdown",
                )
                try:
                    al.emit(
                        event_type="message",
                        event_version="1.0.0",
                        severity="INFO",
                        fields={
                            "message_id": msg_id,
                            "message_role": "assistant",
                            "message_index": message_index,
                            **stored.to_fields(),
                        },
                        session_id=session_id,
                    )
                except Exception:
                    logger.exception("failed to emit message event")
                message_index += 1
            elif block_cls == "ToolUseBlock":
                tool_id = getattr(block, "id", None) or ""
                tool_name = getattr(block, "name", "unknown") or "unknown"
                if tool_id:
                    pending_tool_starts[tool_id] = time.monotonic()
                    pending_tool_names[tool_id] = tool_name
            # ToolResultBlock can appear in AssistantMessage.content too
            elif block_cls == "ToolResultBlock":
                _emit_tool_invocation(
                    block,
                    al=al,
                    session_id=session_id,
                    pending_tool_starts=pending_tool_starts,
                    pending_tool_names=pending_tool_names,
                )

    # UserMessage might carry ToolResultBlock for matching tool_use_id
    elif cls_name == "UserMessage":
        content = getattr(item, "content", None)
        if isinstance(content, list):
            for block in content:
                if block.__class__.__name__ == "ToolResultBlock":
                    _emit_tool_invocation(
                        block,
                        al=al,
                        session_id=session_id,
                        pending_tool_starts=pending_tool_starts,
                        pending_tool_names=pending_tool_names,
                    )

    # ResultMessage: 全体集計を business_event として
    elif cls_name == "ResultMessage":
        try:
            al.emit(
                event_type="business_event",
                event_version="1.0.0",
                severity="INFO",
                fields={
                    "business_domain": "stock_analysis",
                    "action": "claude_query_completed",
                    "attributes": {
                        "duration_ms": int(getattr(item, "duration_ms", 0) or 0),
                        "duration_api_ms": int(getattr(item, "duration_api_ms", 0) or 0),
                        "num_turns": int(getattr(item, "num_turns", 0) or 0),
                        "total_cost_usd": float(getattr(item, "total_cost_usd", 0.0) or 0.0),
                        "is_error": bool(getattr(item, "is_error", False)),
                        "stop_reason": getattr(item, "stop_reason", None),
                    },
                },
                session_id=session_id,
            )
        except Exception:
            logger.exception("failed to emit ResultMessage business_event")

    return message_index


def _emit_tool_invocation(
    block,
    *,
    al,
    session_id: str,
    pending_tool_starts: dict[str, float],
    pending_tool_names: dict[str, str],
) -> None:
    tool_use_id = getattr(block, "tool_use_id", None) or ""
    is_error = bool(getattr(block, "is_error", False))
    started = pending_tool_starts.pop(tool_use_id, None)
    name = pending_tool_names.pop(tool_use_id, "unknown")
    duration_ms = int((time.monotonic() - started) * 1000) if started else 0

    raw = getattr(block, "content", None)
    if isinstance(raw, str):
        size = len(raw.encode("utf-8"))
    elif isinstance(raw, list):
        size = len(json.dumps(raw, ensure_ascii=False).encode("utf-8"))
    else:
        size = 0

    try:
        al.emit(
            event_type="tool_invocation",
            event_version="1.0.0",
            severity="ERROR" if is_error else "INFO",
            fields={
                "tool_name": name,
                "duration_ms": duration_ms,
                "status": "error" if is_error else "success",
                "output_size_bytes": size,
                "retry_count": 0,
            },
            session_id=session_id,
        )
    except Exception:
        logger.exception("failed to emit tool_invocation event")
