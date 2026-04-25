"""分析基盤 (analytics-platform) との接続レイヤ。

stock-analysis-agent の同名モジュールと同設計:
  - プロセス起動時に setup_observability()
  - 終了時に shutdown_observability() で残バッファ flush
  - get_analytics_logger() / get_content_router() / get_tracer() で参照
  - ANALYTICS_ENABLED=false で NoOpSink (テスト / 緊急遮断用)
"""

from __future__ import annotations

from .events import emit_business, emit_error, emit_security
from .setup import (
    NoOpSink,
    get_analytics_logger,
    get_content_router,
    get_tracer,
    get_uploader,
    reset_for_tests,
    setup_observability,
    shutdown_observability,
    start_upload_loop,
)

__all__ = [
    "NoOpSink",
    "emit_business",
    "emit_error",
    "emit_security",
    "get_analytics_logger",
    "get_content_router",
    "get_tracer",
    "get_uploader",
    "reset_for_tests",
    "setup_observability",
    "shutdown_observability",
    "start_upload_loop",
]
