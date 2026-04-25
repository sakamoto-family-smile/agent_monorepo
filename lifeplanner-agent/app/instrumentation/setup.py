"""観測性 (analytics-platform) の初期化と DI コンテナ。

設計:
  - `setup_observability()` を main.py の lifespan で 1 度だけ呼ぶ
  - 以降は `get_analytics_logger()` / `get_content_router()` / `get_tracer()` で参照
  - `gcs` backend (Phase 5 Step 10) では追加で `LocalUploader` を回し、
    raw JSONL を GCS に転送する。バックエンド切替は env 駆動 (analytics_platform.gcp_config)。
  - `start_upload_loop()` は lifespan 内で起動する asyncio タスク。
    定期的に LocalUploader.run_once() を呼び、`uploaded/` (local) または GCS に move する。
  - `shutdown_observability()` で
      1. upload loop タスクを cancel
      2. AnalyticsLogger を flush
      3. LocalUploader を最後に 1 度回す
    の順で cleanup。
  - `ANALYTICS_ENABLED=false` の場合は NoOpSink を使い JSONL 書込なし
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import config
from analytics_platform.gcp_config import (
    build_payload_writer,
    build_upload_transport,
    detect_storage_backend,
)
from analytics_platform.observability.analytics_logger import AnalyticsLogger
from analytics_platform.observability.content import ContentRouter
from analytics_platform.observability.sinks.file_sink import (
    JsonlSink,
    RotatingFileSink,
)
from analytics_platform.observability.tracer import setup_tracer
from analytics_platform.uploader.local_uploader import LocalUploader
from opentelemetry import trace

logger = logging.getLogger(__name__)


def _settings():
    """config.settings を毎回 lookup する (テストで importlib.reload(config) されても追従)。"""
    return config.settings


# ---------------------------------------------------------------------------
# NoOpSink
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
_uploader: LocalUploader | None = None
_upload_task: asyncio.Task | None = None
_initialized: bool = False


def setup_observability() -> None:
    global _analytics_logger, _content_router, _tracer, _uploader, _initialized
    if _initialized:
        return

    s = _settings()
    sink: JsonlSink
    if s.analytics_enabled:
        analytics_root = Path(s.analytics_data_dir)
        raw_dir = analytics_root / "raw"
        payloads_dir = analytics_root / "payloads"
        uploaded_dir = analytics_root / "uploaded"
        dead_letter_dir = analytics_root / "dead_letter"
        for d in (raw_dir, payloads_dir, uploaded_dir, dead_letter_dir):
            d.mkdir(parents=True, exist_ok=True)

        sink = RotatingFileSink(
            root_dir=raw_dir,
            service_name=s.analytics_service_name,
            compress=s.analytics_compress,
        )
        # Content router: env 駆動 (local | gcs)
        # ANALYTICS_STORAGE_BACKEND=gcs かつ ANALYTICS_GCS_BUCKET 設定済なら
        # GCSPayloadWriter、それ以外は LocalFilePayloadWriter にフォールバック。
        payload_writer = build_payload_writer(local_root=payloads_dir)
        _content_router = ContentRouter(
            writer=payload_writer,
            inline_threshold_bytes=s.analytics_content_inline_threshold_bytes,
        )

        # Uploader: env 駆動 (local move | GCS upload)
        upload_transport = build_upload_transport(raw_root=raw_dir)
        _uploader = LocalUploader(
            raw_root=raw_dir,
            uploaded_root=uploaded_dir,
            dead_letter_root=dead_letter_dir,
            transport=upload_transport,
            # Cloud Run 上で書き込み中のファイルを upload しないよう既定 30 秒の余裕。
            # テストでは 0 にして即時 upload を確認する。
            min_age_seconds=s.analytics_uploader_min_age_seconds,
        )

        backend = detect_storage_backend()
        logger.info(
            "analytics enabled (backend=%s, data_dir=%s, service=%s)",
            backend,
            s.analytics_data_dir,
            s.analytics_service_name,
        )
    else:
        # NoOp 経路: payloads ディレクトリは tempfile で動的確保
        import tempfile

        from analytics_platform.observability.content import LocalFilePayloadWriter

        sink = NoOpSink()
        _content_router = ContentRouter(
            writer=LocalFilePayloadWriter(
                root_dir=Path(tempfile.mkdtemp(prefix="analytics_noop_payloads_"))
            ),
            inline_threshold_bytes=s.analytics_content_inline_threshold_bytes,
        )
        _uploader = None
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
        _tracer = trace.get_tracer(s.analytics_service_name)
        logger.info("OTel endpoint unset; spans will not be exported")

    _initialized = True


async def start_upload_loop() -> None:
    """raw JSONL を `LocalUploader` で定期的に upload するバックグラウンドタスクを起動する。

    `analytics_upload_interval_seconds <= 0` の場合は何もしない。
    """
    global _upload_task
    s = _settings()
    if _uploader is None or s.analytics_upload_interval_seconds <= 0:
        logger.info("upload loop disabled (uploader=%s)", _uploader is not None)
        return
    if _upload_task is not None and not _upload_task.done():
        return
    _upload_task = asyncio.create_task(
        _upload_loop(s.analytics_upload_interval_seconds), name="analytics-upload-loop"
    )
    logger.info(
        "upload loop started (interval=%ds)", s.analytics_upload_interval_seconds
    )


async def _upload_loop(interval_seconds: int) -> None:
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            await _run_uploader_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("upload loop iteration failed (continuing)")


async def _run_uploader_once() -> None:
    if _analytics_logger is not None:
        try:
            await _analytics_logger.flush()
        except Exception:
            logger.exception("analytics_logger.flush failed before upload")
    if _uploader is None:
        return
    try:
        outcome = await _uploader.run_once()
        if outcome.total:
            logger.info(
                "uploader cycle: uploaded=%d dead_letter=%d",
                len(outcome.uploaded),
                len(outcome.dead_letter),
            )
    except Exception:
        logger.exception("uploader.run_once failed")


async def shutdown_observability() -> None:
    """プロセス終了時に upload loop を止め、残バッファを flush + 最終 upload。"""
    global _upload_task
    if _upload_task is not None:
        _upload_task.cancel()
        try:
            await _upload_task
        except (asyncio.CancelledError, Exception):
            pass
        _upload_task = None

    if _analytics_logger is not None:
        try:
            n = await _analytics_logger.flush()
            if n:
                logger.info("analytics_logger final flush: %d events", n)
        except Exception:
            logger.exception("analytics_logger final flush failed")

    await _run_uploader_once()


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


def get_uploader() -> LocalUploader | None:
    """テスト / デバッグ用。`ANALYTICS_ENABLED=false` の場合は None。"""
    return _uploader


def reset_for_tests() -> None:
    global _analytics_logger, _content_router, _tracer, _uploader, _upload_task, _initialized
    _analytics_logger = None
    _content_router = None
    _tracer = None
    _uploader = None
    if _upload_task is not None and not _upload_task.done():
        _upload_task.cancel()
    _upload_task = None
    _initialized = False
