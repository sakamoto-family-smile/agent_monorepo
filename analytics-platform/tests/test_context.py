from __future__ import annotations

import re

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from analytics_platform.observability.context import get_current_trace_context


def test_no_span_returns_none() -> None:
    ctx = get_current_trace_context()
    assert ctx["trace_id"] is None
    assert ctx["span_id"] is None


def test_active_span_returns_w3c_hex() -> None:
    # テスト専用の TracerProvider を組み立て、グローバルに差し込む。
    trace.set_tracer_provider(TracerProvider())
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("s"):
        ctx = get_current_trace_context()
        assert ctx["trace_id"] is not None
        assert ctx["span_id"] is not None
        assert re.fullmatch(r"[0-9a-f]{32}", ctx["trace_id"])
        assert re.fullmatch(r"[0-9a-f]{16}", ctx["span_id"])
