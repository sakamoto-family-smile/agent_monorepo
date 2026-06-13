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


# ---------------------------------------------------------------------------
# user_id contextvar (PROPOSAL-0011 follow-up)
# ---------------------------------------------------------------------------


def test_user_id_context_default_none():
    from analytics_platform.observability.context import (
        get_current_user_id,
        set_current_user_id,
    )

    set_current_user_id(None)
    assert get_current_user_id() is None


def test_user_id_context_set_and_get():
    from analytics_platform.observability.context import (
        get_current_user_id,
        set_current_user_id,
    )

    set_current_user_id("U_alice")
    assert get_current_user_id() == "U_alice"
    set_current_user_id(None)


import asyncio


def test_user_id_propagates_to_child_task():
    """asyncio.Task 生成時に context がコピーされ、子タスクでも参照できる。"""
    from analytics_platform.observability.context import (
        get_current_user_id,
        set_current_user_id,
    )

    async def main():
        set_current_user_id("U_task")

        async def child():
            return get_current_user_id()

        return await asyncio.create_task(child())

    assert asyncio.run(main()) == "U_task"
    set_current_user_id(None)
