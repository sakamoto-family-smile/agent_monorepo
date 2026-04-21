"""structlog 設定。

全ての `logger.info(...)` / `logger.error(...)` 等に:
  - `trace_id` / `span_id` (OTel Context から)
  - `timestamp` (ISO 8601 UTC)
  - `level`
を自動注入する。JSON 出力なのでそのまま業務ログ basin に流してもよいが、
stdout は人間向け、本番基盤は `AnalyticsLogger` 側に送るのが推奨 (設計書 §10.3)。
"""

from __future__ import annotations

import logging

import structlog

from .context import get_current_trace_context


def _inject_trace_context(
    _logger: logging.Logger, _method: str, event_dict: dict[str, object]
) -> dict[str, object]:
    ctx = get_current_trace_context()
    if ctx["trace_id"]:
        event_dict.setdefault("trace_id", ctx["trace_id"])
        event_dict.setdefault("span_id", ctx["span_id"])
    return event_dict


def configure_structlog(level: str = "INFO") -> None:
    """プロセス全体で 1 度呼ぶ。"""
    logging.basicConfig(level=level.upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _inject_trace_context,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
