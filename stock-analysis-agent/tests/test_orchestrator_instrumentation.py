"""orchestrator.run_analysis の計装テスト。

実 LLM / 実ファイル取得は全部モックし、AnalyticsLogger に流れるイベントだけ検証する。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

import instrumentation
from analytics_platform.observability.analytics_logger import AnalyticsLogger


# ---------------------------------------------------------------------------
# モックシンク (バッファに全イベント文字列を貯める)
# ---------------------------------------------------------------------------


@dataclass
class _MemorySink:
    written: list[str] = field(default_factory=list)

    async def write_batch(self, lines: list[str]) -> None:
        self.written.extend(lines)


# ---------------------------------------------------------------------------
# Claude Agent SDK のモックメッセージクラス
# ---------------------------------------------------------------------------


# 注: orchestrator は cls.__name__ で SDK メッセージ種別を判定するため、
# モッククラス名は SDK と完全一致させる必要がある (アンダースコア prefix 不可)。


@dataclass
class TextBlock:
    text: str


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict


@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: str | list[dict] | None = None
    is_error: bool | None = None


@dataclass
class AssistantMessage:
    content: list
    model: str = "claude-opus-4-7"
    usage: dict | None = None
    stop_reason: str | None = "end_turn"


@dataclass
class UserMessage:
    content: list


@dataclass
class ResultMessage:
    duration_ms: int = 1234
    duration_api_ms: int = 800
    is_error: bool = False
    num_turns: int = 3
    session_id: str = "sess_abc"
    stop_reason: str | None = "end_turn"
    total_cost_usd: float | None = 0.05
    usage: dict | None = None


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sink() -> _MemorySink:
    return _MemorySink()


@pytest.fixture(autouse=True)
def _setup(monkeypatch, tmp_path: Path, sink):
    """instrumentation を MemorySink で組み立てて差し込む。"""
    from config import settings

    instrumentation.reset_for_tests()
    monkeypatch.setattr(settings, "analytics_enabled", True)
    monkeypatch.setattr(settings, "analytics_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "")

    # setup_observability を経由しつつ sink だけ差し替える
    instrumentation.setup_observability()
    al = AnalyticsLogger(
        service_name=settings.analytics_service_name,
        service_version=settings.service_version,
        environment=settings.app_env,
        sink=sink,
    )
    monkeypatch.setattr(instrumentation.setup, "_analytics_logger", al)
    yield
    instrumentation.reset_for_tests()


def _events(sink: _MemorySink) -> list[dict]:
    return [json.loads(line) for line in sink.written]


def _events_by_type(sink: _MemorySink) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for ev in _events(sink):
        grouped.setdefault(ev["event_type"], []).append(ev)
    return grouped


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


async def test_run_analysis_emits_full_lifecycle(monkeypatch, sink, tmp_path: Path):
    """ハッピーパス: ticker resolve → 取得 → LLM 1 turn (ツール使用 1 回) → 保存 → end."""
    from agents import orchestrator
    from models.stock import AnalysisRequest

    # 1) ticker_resolver / data_collection / chart_generator / save_report のモック
    async def _fake_resolve(query: str):
        from models.stock import ResolveResult
        return ResolveResult(
            ticker="7203.T",
            confidence=0.95,
            source="dict",
            company_name="トヨタ自動車",
        )

    async def _fake_ohlcv(ticker, period):
        return []

    async def _fake_fundamentals(ticker):
        return None

    async def _maybe_none(*a, **kw):
        return None

    async def _fake_save_report(*, ticker, company_name, report_data):
        return 42

    def _fake_chart(ticker, ohlcv, charts_dir):
        return None

    monkeypatch.setattr(orchestrator, "resolve_ticker", _fake_resolve)
    monkeypatch.setattr(orchestrator, "fetch_ohlcv", _fake_ohlcv)
    monkeypatch.setattr(orchestrator, "fetch_fundamentals", _fake_fundamentals)
    monkeypatch.setattr(orchestrator, "compute_indicators", lambda _o: None)
    monkeypatch.setattr(orchestrator, "generate_chart", _fake_chart)
    monkeypatch.setattr(orchestrator, "save_report", _fake_save_report)
    monkeypatch.setattr(orchestrator, "_write_mcp_config", lambda *a, **kw: None)

    # 2) Claude Agent SDK の query() を fake stream に差し替え
    async def _fake_query(prompt, options):
        # ツール呼出 1 回 (web_search) → ツール結果 → 最終応答
        yield AssistantMessage(
            content=[ToolUseBlock(id="tu_1", name="mcp__brave-search__search", input={})],
            usage={"input_tokens": 1000, "output_tokens": 50, "cache_read_input_tokens": 800},
        )
        yield UserMessage(
            content=[ToolResultBlock(tool_use_id="tu_1", content="news result", is_error=False)]
        )
        yield AssistantMessage(
            content=[TextBlock(text="トヨタの分析結果は以下の通りです...")],
            usage={"input_tokens": 1500, "output_tokens": 300},
        )
        yield ResultMessage()

    monkeypatch.setattr(orchestrator, "query", _fake_query)

    # 3) 実行
    request = AnalysisRequest(
        query="トヨタ自動車", period="1mo", analysis_types=["technical", "fundamental"]
    )
    events = []
    async for ev in orchestrator.run_analysis(request):
        events.append(ev)

    # 4) 検証 — 全体の flow event
    grouped = _events_by_type(sink)
    assert "conversation_event" in grouped
    phases = [e["conversation_phase"] for e in grouped["conversation_event"]]
    assert phases == ["started", "ended"]

    # 5) ticker_resolved
    biz = grouped.get("business_event", [])
    actions = [e["action"] for e in biz]
    assert "ticker_resolved" in actions
    assert "claude_query_completed" in actions
    assert "report_saved" in actions

    # 6) llm_call が 2 回 (AssistantMessage が 2 個)
    llm_calls = grouped.get("llm_call", [])
    assert len(llm_calls) == 2
    assert llm_calls[0]["input_tokens"] == 1000
    assert llm_calls[0]["cache_read_tokens"] == 800
    assert llm_calls[1]["input_tokens"] == 1500
    assert llm_calls[1]["output_tokens"] == 300

    # 7) tool_invocation が 1 回
    tools = grouped.get("tool_invocation", [])
    assert len(tools) == 1
    assert tools[0]["tool_name"] == "mcp__brave-search__search"
    assert tools[0]["status"] == "success"

    # 8) message が 1 回 (assistant text)
    msgs = grouped.get("message", [])
    assert len(msgs) == 1
    assert msgs[0]["message_role"] == "assistant"

    # 9) 全てのイベントに session_id / trace_id 系が一貫
    session_ids = {e["session_id"] for e in _events(sink)}
    assert len(session_ids) == 1


async def test_run_analysis_emits_error_event_on_failure(monkeypatch, sink, tmp_path: Path):
    """orchestrator 内で例外が出たら error_event + conversation_event(aborted)。"""
    from agents import orchestrator
    from models.stock import AnalysisRequest

    async def _failing_resolve(query: str):
        raise RuntimeError("boom")

    monkeypatch.setattr(orchestrator, "resolve_ticker", _failing_resolve)

    request = AnalysisRequest(query="bad", period="1mo", analysis_types=["technical"])
    with pytest.raises(RuntimeError):
        async for _ev in orchestrator.run_analysis(request):
            pass

    grouped = _events_by_type(sink)
    assert "error_event" in grouped
    err = grouped["error_event"][0]
    assert err["error_type"] == "RuntimeError"
    assert err["error_category"] == "internal"

    phases = [e["conversation_phase"] for e in grouped["conversation_event"]]
    assert "started" in phases and "aborted" in phases


async def test_failing_tool_emits_status_error(monkeypatch, sink, tmp_path: Path):
    """ToolResultBlock(is_error=True) → tool_invocation の status='error'。"""
    from agents import orchestrator
    from models.stock import AnalysisRequest

    async def _fake_resolve(query: str):
        from models.stock import ResolveResult
        return ResolveResult(ticker="X", confidence=0.9, source="dict", company_name="X")

    monkeypatch.setattr(orchestrator, "resolve_ticker", _fake_resolve)
    async def _empty_list(*a, **kw):
        return []

    async def _none(*a, **kw):
        return None

    monkeypatch.setattr(orchestrator, "fetch_ohlcv", _empty_list)
    monkeypatch.setattr(orchestrator, "fetch_fundamentals", _none)
    monkeypatch.setattr(orchestrator, "compute_indicators", lambda _o: None)
    monkeypatch.setattr(orchestrator, "generate_chart", lambda *a, **kw: None)

    async def _fake_save(*, ticker, company_name, report_data):
        return 1

    monkeypatch.setattr(orchestrator, "save_report", _fake_save)
    monkeypatch.setattr(orchestrator, "_write_mcp_config", lambda *a, **kw: None)

    async def _fake_query(prompt, options):
        yield AssistantMessage(
            content=[ToolUseBlock(id="tu_x", name="failing_tool", input={})],
            usage={"input_tokens": 1, "output_tokens": 1},
        )
        yield UserMessage(
            content=[ToolResultBlock(tool_use_id="tu_x", content="oops", is_error=True)]
        )
        yield ResultMessage()

    monkeypatch.setattr(orchestrator, "query", _fake_query)

    request = AnalysisRequest(query="x", period="1mo", analysis_types=["technical"])
    async for _ev in orchestrator.run_analysis(request):
        pass

    grouped = _events_by_type(sink)
    tools = grouped["tool_invocation"]
    assert tools[0]["status"] == "error"
    assert tools[0]["severity"] == "ERROR"


async def _async_none():
    return None
