import asyncio
import json
import logging
import os
from datetime import datetime
from typing import AsyncIterator, Optional

from claude_agent_sdk import query, ClaudeAgentOptions

from models.stock import AnalysisRequest, AnalysisReport, SentimentData
from agents.ticker_resolver import resolve_ticker
from agents.data_collection import fetch_ohlcv, fetch_fundamentals
from agents.technical_analysis import compute_indicators
from agents.chart_generator import generate_chart
from services.database import save_report
from config import settings

logger = logging.getLogger(__name__)

_INTER_MESSAGE_TIMEOUT = int(os.getenv("AGENT_MESSAGE_TIMEOUT_SECONDS", "120"))


def _build_analysis_prompt(
    ticker: str,
    company_name: Optional[str],
    ohlcv_summary: str,
    technical_summary: str,
    fundamental_summary: str,
) -> str:
    name = company_name or ticker
    return f"""あなたは株式アナリストです。以下のデータを元に、{name}（{ticker}）の詳細な投資分析レポートを日本語で作成してください。

## 価格データ（直近）
{ohlcv_summary}

## テクニカル指標
{technical_summary}

## ファンダメンタルズ
{fundamental_summary}

## 分析指示
1. **テクニカル分析**: トレンド、サポート/レジスタンス、オシレーター（RSI, MACD）、ボリンジャーバンドの状態を分析してください
2. **ファンダメンタル分析**: バリュエーション（PER, PBR）、収益性、財務健全性を評価してください
3. **センチメント分析**: Brave Searchを使って最新ニュースを検索し、市場センチメントを分析してください（キーワード: "{name} 株価 ニュース"）
4. **総合評価**: 強気/中立/弱気の判断と、その根拠を明確に示してください
5. **リスク要因**: 主要なダウンサイドリスクを列挙してください

レポートは投資家が意思決定に使えるよう、具体的かつ客観的に記述してください。"""


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
    """Run full stock analysis pipeline."""
    # Step 1: Resolve ticker
    resolve_result = await resolve_ticker(request.query)
    ticker = resolve_result.ticker
    company_name = resolve_result.company_name or request.query

    logger.info(
        "Resolved '%s' -> %s (confidence=%.2f, source=%s)",
        request.query, ticker, resolve_result.confidence, resolve_result.source
    )

    # Step 2: Fetch data in parallel
    ohlcv, fundamentals = await asyncio.gather(
        fetch_ohlcv(ticker, request.period),
        fetch_fundamentals(ticker) if "fundamental" in request.analysis_types else asyncio.coroutine(lambda: None)(),
    )

    # Step 3: Technical analysis
    technical = None
    if "technical" in request.analysis_types:
        technical = compute_indicators(ohlcv)

    # Step 4: Generate chart
    chart_path = generate_chart(ticker, ohlcv, settings.charts_dir)

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

    prompt = _build_analysis_prompt(
        ticker=ticker,
        company_name=company_name,
        ohlcv_summary=_format_ohlcv_summary(ohlcv),
        technical_summary=_format_technical_summary(technical),
        fundamental_summary=_format_fundamental_summary(fundamentals),
    )

    options = ClaudeAgentOptions(
        model="claude-opus-4-6",
        permission_mode="bypassPermissions",
        cwd=workspace_dir,
        system_prompt="あなたは日本の株式市場に精通したプロのアナリストです。データに基づいた客観的な分析を行い、日本語でレポートを作成してください。",
        env={
            "HOME": "/tmp",
            "ANTHROPIC_API_KEY": "",
            "CLAUDE_CODE_OAUTH_TOKEN": os.getenv("ANTHROPIC_API_KEY", ""),
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

    async def _producer() -> None:
        try:
            async for msg in query(prompt=prompt, options=options):
                await queue.put(msg)
        except Exception as exc:
            logger.exception("orchestrator producer error: %s", exc)
            await queue.put(exc)
        finally:
            await queue.put(_sentinel)

    task = asyncio.create_task(_producer())

    try:
        while True:
            try:
                item = await asyncio.wait_for(
                    queue.get(), timeout=_INTER_MESSAGE_TIMEOUT
                )
            except asyncio.TimeoutError:
                task.cancel()
                raise TimeoutError(f"エージェントが{_INTER_MESSAGE_TIMEOUT}秒以上応答しませんでした。")

            if item is _sentinel:
                break
            if isinstance(item, Exception):
                raise item

            # Collect assistant text for report
            msg_type = getattr(item, 'type', None) or item.__class__.__name__
            if hasattr(item, 'content'):
                for block in (item.content or []):
                    if hasattr(block, 'text'):
                        report_text_parts.append(block.text)

            yield {"type": msg_type, "data": str(item)}

    finally:
        if not task.done():
            task.cancel()
        import contextlib
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    # Save report
    report.report_text = "\n".join(report_text_parts)
    report_id = await save_report(
        ticker=ticker,
        company_name=company_name,
        report_data=report.model_dump(mode="json"),
    )

    yield {
        "type": "report_complete",
        "report_id": report_id,
        "ticker": ticker,
        "company_name": company_name,
        "report": report.model_dump(mode="json"),
    }
