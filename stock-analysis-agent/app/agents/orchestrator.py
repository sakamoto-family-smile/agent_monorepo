import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from datetime import datetime
from typing import AsyncIterator, Optional

from claude_agent_sdk import query, ClaudeAgentOptions

from analytics_platform.observability.hashing import sha256_prefixed
from models.stock import AnalysisRequest, AnalysisReport, SentimentData
from agents.ticker_resolver import resolve_ticker
from agents.data_collection import fetch_ohlcv, fetch_fundamentals
from agents.technical_analysis import compute_indicators
from agents.chart_generator import generate_chart
from instrumentation import get_analytics_logger, get_content_router, get_tracer
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
