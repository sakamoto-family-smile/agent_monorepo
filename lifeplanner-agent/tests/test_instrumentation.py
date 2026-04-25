"""instrumentation モジュール (setup / DI / NoOpSink + helpers) のユニットテスト。"""

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
    assert (tmp_path / "raw").exists()
    assert (tmp_path / "payloads").exists()


async def test_shutdown_flushes_buffer(monkeypatch, tmp_path: Path):
    from config import settings

    monkeypatch.setattr(settings, "analytics_enabled", True)
    monkeypatch.setattr(settings, "analytics_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "")
    # min_age=30s なので shutdown 時の最終 upload で raw が pickup されない。
    # 「flush だけは走る」ことを確認したいので raw に残っていれば OK とする。
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
    """既定 (`ANALYTICS_STORAGE_BACKEND=local`) では従来通り LocalFilePayloadWriter。"""
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
    assert (tmp_path / "raw").exists()
    assert (tmp_path / "uploaded").exists()
    assert (tmp_path / "dead_letter").exists()


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


# ---------------------------------------------------------------------------
# helpers (emit_business / emit_error / emit_security)
# ---------------------------------------------------------------------------


def test_emit_business_silent_without_setup():
    # setup していなくてもエラーにならず黙って無視される
    from instrumentation import emit_business, emit_error, emit_security

    emit_business(domain="x", action="y")
    emit_error(error=ValueError("z"))
    emit_security(guard_name="model_armor", check_type="x", action_taken="allowed")


async def test_emit_business_writes_jsonl(monkeypatch, tmp_path: Path):
    from config import settings
    from instrumentation import emit_business

    monkeypatch.setattr(settings, "analytics_enabled", True)
    monkeypatch.setattr(settings, "analytics_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "")
    instrumentation.setup_observability()

    emit_business(
        domain="csv_import",
        action="csv_imported",
        resource_type="batch",
        resource_id="2026-04",
        attributes={"imported": 100},
        user_id="u_1",
    )
    al = instrumentation.get_analytics_logger()
    await al.flush()

    files = list((tmp_path / "raw").rglob("*.jsonl"))
    assert len(files) == 1
    import json

    line = files[0].read_text().splitlines()[0]
    obj = json.loads(line)
    assert obj["event_type"] == "business_event"
    assert obj["business_domain"] == "csv_import"
    assert obj["action"] == "csv_imported"
    assert obj["attributes"]["imported"] == 100
    assert obj["user_id"] == "u_1"


async def test_emit_error_writes_jsonl(monkeypatch, tmp_path: Path):
    from config import settings
    from instrumentation import emit_error

    monkeypatch.setattr(settings, "analytics_enabled", True)
    monkeypatch.setattr(settings, "analytics_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "")
    instrumentation.setup_observability()

    emit_error(
        error=ValueError("test"),
        category="validation",
        user_id="u_2",
    )
    al = instrumentation.get_analytics_logger()
    await al.flush()

    files = list((tmp_path / "raw").rglob("*.jsonl"))
    assert len(files) == 1
    import json

    obj = json.loads(files[0].read_text().splitlines()[0])
    assert obj["event_type"] == "error_event"
    assert obj["error_type"] == "ValueError"
    assert obj["error_category"] == "validation"
