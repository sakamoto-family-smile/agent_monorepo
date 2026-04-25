"""instrumentation モジュール (setup / DI / GCP backend 切替) のユニットテスト。

PR #46 (stock-analysis-agent) / PR #47 (lifeplanner-agent) と同じレシピ。
"""

from __future__ import annotations

from pathlib import Path

import instrumentation
import pytest


@pytest.fixture(autouse=True)
def _reset_instrumentation():
    instrumentation.reset_for_tests()
    yield
    instrumentation.reset_for_tests()


def test_get_before_setup_raises():
    with pytest.raises(RuntimeError):
        instrumentation.get_analytics_logger()
    with pytest.raises(RuntimeError):
        instrumentation.get_content_router()
    with pytest.raises(RuntimeError):
        instrumentation.get_tracer()


async def test_setup_with_analytics_disabled(monkeypatch, tmp_path: Path):
    from config import settings

    monkeypatch.setattr(settings, "analytics_enabled", False)
    monkeypatch.setattr(settings, "analytics_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "")

    instrumentation.setup_observability()

    al = instrumentation.get_analytics_logger()
    al.emit(
        event_type="business_event",
        event_version="1.0.0",
        severity="INFO",
        fields={"business_domain": "test", "action": "noop"},
    )
    await al.flush()
    assert not list(tmp_path.rglob("*.jsonl"))


def test_setup_creates_dirs_when_enabled(monkeypatch, tmp_path: Path):
    from config import settings

    monkeypatch.setattr(settings, "analytics_enabled", True)
    monkeypatch.setattr(settings, "analytics_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "")

    instrumentation.setup_observability()
    for sub in ("raw", "payloads", "uploaded", "dead_letter"):
        assert (tmp_path / sub).exists()


async def test_shutdown_flushes_buffer(monkeypatch, tmp_path: Path):
    from config import settings

    monkeypatch.setattr(settings, "analytics_enabled", True)
    monkeypatch.setattr(settings, "analytics_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "")
    monkeypatch.setattr(settings, "analytics_uploader_min_age_seconds", 30.0)

    instrumentation.setup_observability()
    al = instrumentation.get_analytics_logger()
    al.emit(
        event_type="business_event",
        event_version="1.0.0",
        severity="INFO",
        fields={"business_domain": "t", "action": "x"},
    )
    assert al.buffer_size == 1
    await instrumentation.shutdown_observability()
    assert al.buffer_size == 0
    raw_files = list((tmp_path / "raw").rglob("*.jsonl"))
    uploaded_files = list((tmp_path / "uploaded").rglob("*.jsonl"))
    assert raw_files or uploaded_files


# ---------------------------------------------------------------------------
# Phase 5 Step 10: GCP backend 切替 + LocalUploader 連携
# ---------------------------------------------------------------------------


def test_setup_with_local_backend_uses_local_payload_writer(monkeypatch, tmp_path: Path):
    """既定 (`ANALYTICS_STORAGE_BACKEND=local`) では LocalFilePayloadWriter。"""
    from analytics_platform.observability.content import LocalFilePayloadWriter

    from config import settings

    monkeypatch.setenv("ANALYTICS_STORAGE_BACKEND", "local")
    monkeypatch.setattr(settings, "analytics_enabled", True)
    monkeypatch.setattr(settings, "analytics_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "")

    instrumentation.setup_observability()

    cr = instrumentation.get_content_router()
    assert isinstance(cr.writer, LocalFilePayloadWriter)


def test_setup_with_gcs_backend_falls_back_when_bucket_missing(
    monkeypatch, tmp_path: Path
):
    """`backend=gcs` でも `ANALYTICS_GCS_BUCKET` 未設定なら local にフォールバック。"""
    from analytics_platform.observability.content import LocalFilePayloadWriter

    from config import settings

    monkeypatch.setenv("ANALYTICS_STORAGE_BACKEND", "gcs")
    monkeypatch.delenv("ANALYTICS_GCS_BUCKET", raising=False)
    monkeypatch.setattr(settings, "analytics_enabled", True)
    monkeypatch.setattr(settings, "analytics_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "")

    instrumentation.setup_observability()

    cr = instrumentation.get_content_router()
    assert isinstance(cr.writer, LocalFilePayloadWriter)


def test_setup_creates_uploader_when_analytics_enabled(monkeypatch, tmp_path: Path):
    from analytics_platform.uploader.local_uploader import LocalUploader

    from config import settings

    monkeypatch.setenv("ANALYTICS_STORAGE_BACKEND", "local")
    monkeypatch.setattr(settings, "analytics_enabled", True)
    monkeypatch.setattr(settings, "analytics_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "")

    instrumentation.setup_observability()

    uploader = instrumentation.get_uploader()
    assert isinstance(uploader, LocalUploader)


def test_uploader_is_none_when_analytics_disabled(monkeypatch, tmp_path: Path):
    from config import settings

    monkeypatch.setattr(settings, "analytics_enabled", False)
    monkeypatch.setattr(settings, "analytics_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "")

    instrumentation.setup_observability()
    assert instrumentation.get_uploader() is None


async def test_start_upload_loop_skips_when_interval_zero(monkeypatch, tmp_path: Path):
    from config import settings

    monkeypatch.setattr(settings, "analytics_enabled", True)
    monkeypatch.setattr(settings, "analytics_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "")
    monkeypatch.setattr(settings, "analytics_upload_interval_seconds", 0)

    instrumentation.setup_observability()
    await instrumentation.start_upload_loop()

    from instrumentation import setup as _setup_mod

    assert _setup_mod._upload_task is None


async def test_shutdown_runs_uploader_one_last_time(monkeypatch, tmp_path: Path):
    """shutdown_observability は最後に uploader.run_once() を呼ぶ (raw -> uploaded を移動)。"""
    from config import settings

    monkeypatch.setattr(settings, "analytics_enabled", True)
    monkeypatch.setattr(settings, "analytics_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "")
    monkeypatch.setattr(settings, "analytics_uploader_min_age_seconds", 0.0)

    instrumentation.setup_observability()
    al = instrumentation.get_analytics_logger()
    al.emit(
        event_type="business_event",
        event_version="1.0.0",
        severity="INFO",
        fields={"business_domain": "t", "action": "x"},
    )

    await instrumentation.shutdown_observability()

    uploaded_files = list((tmp_path / "uploaded").rglob("*.jsonl"))
    raw_files = list((tmp_path / "raw").rglob("*.jsonl"))
    assert uploaded_files, "expected JSONL to be uploaded"
    assert not raw_files, "raw should be empty after final upload"
