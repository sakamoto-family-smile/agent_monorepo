"""`analytics-platform` 連携ヘルパ (optional)。

`analytics-platform` の `AnalyticsLogger` を受け取り、`on_call` コールバックを
返す。各消費エージェントが共通処理を再実装せずに済むようにする。

`analytics-platform` への hard 依存を避けるため、本モジュールを import しても
エラーにならないようにしている (`AnalyticsLogger` は Protocol で後方互換をとる)。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol

from .types import LlmCallEvent, OnCallCallback

logger = logging.getLogger(__name__)


class _AnalyticsLoggerLike(Protocol):
    """`analytics_platform.observability.analytics_logger.AnalyticsLogger` 互換の最小シグネチャ。"""

    def emit(
        self,
        *,
        event_type: str,
        event_version: str,
        severity: str,
        fields: dict[str, Any],
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> str: ...


LoggerFactory = Callable[[], _AnalyticsLoggerLike | None]
"""`AnalyticsLogger` を lazy 取得するためのファクトリ。

`setup_observability()` が呼ばれる前に `on_call` が定義されるケースに備え、
コールバック実行時に解決する。取得失敗時は None を返して静かに無視する。
"""


def make_analytics_on_call(logger_factory: LoggerFactory) -> OnCallCallback:
    """`analytics-platform` の `llm_call` event を emit する `on_call` を生成。

    使用例:
        def _get_logger():
            try:
                from instrumentation import get_analytics_logger
                return get_analytics_logger()
            except Exception:
                return None

        client = AnthropicLLMClient(
            api_key=...,
            model=...,
            max_tokens=1024,
            on_call=make_analytics_on_call(_get_logger),
        )
    """

    def _on_call(event: LlmCallEvent) -> None:
        al = logger_factory()
        if al is None:
            return

        fields: dict[str, Any] = {
            "llm_provider": event.get("provider", "unknown"),
            "llm_model": event.get("model", "unknown"),
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "latency_ms": event.get("latency_ms", 0),
        }
        resp = event.get("resp")
        if resp is not None:
            usage = getattr(resp, "usage", None)
            if usage is not None:
                fields["input_tokens"] = int(getattr(usage, "input_tokens", 0) or 0)
                fields["output_tokens"] = int(getattr(usage, "output_tokens", 0) or 0)
                fields["cache_read_tokens"] = int(
                    getattr(usage, "cache_read_input_tokens", 0) or 0
                )
                fields["cache_creation_tokens"] = int(
                    getattr(usage, "cache_creation_input_tokens", 0) or 0
                )
            stop_reason = getattr(resp, "stop_reason", None)
            if stop_reason:
                fields["stop_reason"] = stop_reason

        severity = "INFO"
        err = event.get("error")
        if err is not None:
            fields["error_type"] = type(err).__name__
            fields["error_message"] = str(err)[:1000]
            severity = "ERROR"

        try:
            al.emit(
                event_type="llm_call",
                event_version="1.0.0",
                severity=severity,
                fields=fields,
            )
        except Exception:
            logger.exception("failed to emit llm_call event (non-fatal)")

    return _on_call
