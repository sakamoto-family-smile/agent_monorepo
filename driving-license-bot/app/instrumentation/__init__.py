"""観測性 (analytics-platform) の初期化と DI コンテナ。"""

from app.instrumentation.events import emit_business_event, emit_error_event
from app.instrumentation.setup import (
    get_analytics_logger,
    get_content_router,
    get_tracer,
    reset_for_tests,
    setup_observability,
    shutdown_observability,
)

__all__ = [
    "emit_business_event",
    "emit_error_event",
    "get_analytics_logger",
    "get_content_router",
    "get_tracer",
    "reset_for_tests",
    "setup_observability",
    "shutdown_observability",
]
