"""分析基盤 (analytics-platform) との接続レイヤ。

役割:
  - プロセス起動時に OTel TracerProvider を初期化
  - AnalyticsLogger / ContentRouter / Tracer の DI を集中管理
  - `ANALYTICS_ENABLED=false` の時は AnalyticsLogger を NoOpSink で構築し、
    既存コードからは透過的に呼べる (本番無効化 / テスト用)
"""

from __future__ import annotations

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
    "get_analytics_logger",
    "get_content_router",
    "get_tracer",
    "get_uploader",
    "reset_for_tests",
    "setup_observability",
    "shutdown_observability",
    "start_upload_loop",
]
