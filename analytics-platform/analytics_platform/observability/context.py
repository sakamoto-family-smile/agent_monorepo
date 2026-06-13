"""OTel Context から現在の trace_id / span_id を取り出すヘルパー。

trace_id は 128bit 整数で保持されているので、W3C 標準の 32 文字 16 進文字列に変換する。
span_id は 64bit 整数で保持されているので、16 文字 16 進文字列に変換する。

OTel が未初期化 or span が無い場合は両方 None を返す。
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TypedDict

from opentelemetry import trace


class TraceContext(TypedDict):
    trace_id: str | None
    span_id: str | None


def get_current_trace_context() -> TraceContext:
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if not ctx.is_valid:
        return {"trace_id": None, "span_id": None}
    return {
        "trace_id": format(ctx.trace_id, "032x"),
        "span_id": format(ctx.span_id, "016x"),
    }


# ---------------------------------------------------------------------------
# user_id context (PROPOSAL-0011 follow-up: ユーザー別利用統計)
# ---------------------------------------------------------------------------
#
# リクエスト入口 (webhook handler / worker task) で `set_current_user_id()` を
# 一度呼ぶと、同一 async context 内の `AnalyticsLogger.emit()` が user_id を
# 自動付与する (emit の明示引数が優先)。contextvars は asyncio.Task 生成時に
# コピーされるため、BackgroundTasks / create_task 配下にも伝播する。

_current_user_id: ContextVar[str | None] = ContextVar("analytics_user_id", default=None)


def set_current_user_id(user_id: str | None) -> None:
    """現在の async context の user_id を設定する (None でクリア)。"""
    _current_user_id.set(user_id)


def get_current_user_id() -> str | None:
    return _current_user_id.get()
