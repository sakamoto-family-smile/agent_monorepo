"""観測性 (analytics-platform) の初期化と DI コンテナ。

設計:
  - `setup_observability()` を `main.py` の lifespan で 1 度だけ呼ぶ
  - 以降は `get_analytics_logger()` / `get_content_router()` / `get_tracer()` で参照
  - `shutdown_observability()` で残バッファを flush してから終了
  - `ANALYTICS_ENABLED=false` の場合は NoOpSink を使い、JSONL は書かれない
    (テスト用 / 本番無効化用)
"""

from __future__ import annotations

import logging
from pathlib import Path

from analytics_platform.observability.analytics_logger import AnalyticsLogger
from analytics_platform.observability.content import (
    ContentRouter,
    LocalFilePayloadWriter,
)
from analytics_platform.observability.sinks.file_sink import (
    JsonlSink,
    RotatingFileSink,
)
from analytics_platform.observability.tracer import setup_tracer
from opentelemetry import trace

import config

logger = logging.getLogger(__name__)


def _settings():
    """config.settings を毎回 lookup する (テストで importlib.reload(config) されても追従)。"""
    return config.settings


# ---------------------------------------------------------------------------
# NoOpSink (テスト / 無効化用)
# ---------------------------------------------------------------------------


class NoOpSink:
    """write_batch を呼んでも何もしない。AnalyticsLogger 互換の sink。"""

    async def write_batch(self, lines: list[str]) -> None:  # noqa: D401
        return None


# ---------------------------------------------------------------------------
# DI コンテナ (シングルトン)
# ---------------------------------------------------------------------------

_analytics_logger: AnalyticsLogger | None = None
_content_router: ContentRouter | None = None
_tracer: trace.Tracer | None = None
_initialized: bool = False


def setup_observability() -> None:
    """プロセス起動時に 1 度だけ呼ぶ。"""
    global _analytics_logger, _content_router, _tracer, _initialized
    if _initialized:
        return

    s = _settings()
    sink: JsonlSink
    if s.analytics_enabled:
        raw_dir = Path(s.analytics_data_dir) / "raw"
        payloads_dir = Path(s.analytics_data_dir) / "payloads"
        raw_dir.mkdir(parents=True, exist_ok=True)
        payloads_dir.mkdir(parents=True, exist_ok=True)

        sink = RotatingFileSink(
            root_dir=raw_dir,
            service_name=s.analytics_service_name,
            compress=s.analytics_compress,
        )
        _content_router = ContentRouter(
            writer=LocalFilePayloadWriter(root_dir=payloads_dir),
            inline_threshold_bytes=s.analytics_content_inline_threshold_bytes,
        )
        logger.info(
            "analytics enabled (data_dir=%s, service=%s)",
            s.analytics_data_dir,
            s.analytics_service_name,
        )
    else:
        sink = NoOpSink()
        _content_router = ContentRouter(
            writer=LocalFilePayloadWriter(root_dir=Path("/tmp/_noop_payloads")),
            inline_threshold_bytes=s.analytics_content_inline_threshold_bytes,
        )
        logger.info("analytics disabled (NoOpSink)")

    _analytics_logger = AnalyticsLogger(
        service_name=s.analytics_service_name,
        service_version=s.service_version,
        environment=s.app_env,
        sink=sink,
    )

    if s.otel_exporter_otlp_endpoint:
        _tracer = setup_tracer(
            service_name=s.analytics_service_name,
            service_version=s.service_version,
            environment=s.app_env,
            otlp_endpoint=s.otel_exporter_otlp_endpoint,
            otlp_headers=s.otel_exporter_otlp_headers,
            sampling_ratio=s.otel_sampling_ratio,
        )
    else:
        # OTel endpoint 未設定でも tracer 自体は取れる (NoOp 相当)
        _tracer = trace.get_tracer(s.analytics_service_name)
        logger.info("OTel endpoint unset; spans will not be exported")

    _initialized = True


async def shutdown_observability() -> None:
    """プロセス終了時に残バッファを flush。"""
    global _analytics_logger
    if _analytics_logger is None:
        return
    try:
        n = await _analytics_logger.flush()
        if n:
            logger.info("analytics_logger final flush: %d events", n)
    except Exception:
        logger.exception("analytics_logger final flush failed")


def get_analytics_logger() -> AnalyticsLogger:
    if _analytics_logger is None:
        raise RuntimeError("setup_observability() not called")
    return _analytics_logger


def get_content_router() -> ContentRouter:
    if _content_router is None:
        raise RuntimeError("setup_observability() not called")
    return _content_router


def get_tracer() -> trace.Tracer:
    if _tracer is None:
        raise RuntimeError("setup_observability() not called")
    return _tracer


def reset_for_tests() -> None:
    """テスト用: グローバル state をクリア。"""
    global _analytics_logger, _content_router, _tracer, _initialized
    _analytics_logger = None
    _content_router = None
    _tracer = None
    _initialized = False
