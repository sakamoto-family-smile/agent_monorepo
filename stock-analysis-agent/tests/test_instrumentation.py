"""instrumentation モジュール (setup / DI / NoOpSink) のユニットテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

import instrumentation


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
    cr = instrumentation.get_content_router()
    assert al is not None
    assert cr is not None

    eid = al.emit(
        event_type="business_event",
        event_version="1.0.0",
        severity="INFO",
        fields={"business_domain": "test", "action": "noop"},
    )
    assert eid

    # NoOpSink なので flush しても何もファイルが作られない
    await al.flush()
    assert not list(tmp_path.rglob("*.jsonl"))


def test_setup_with_analytics_enabled_creates_dirs(monkeypatch, tmp_path: Path):
    from config import settings

    monkeypatch.setattr(settings, "analytics_enabled", True)
    monkeypatch.setattr(settings, "analytics_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "")

    instrumentation.setup_observability()

    assert (tmp_path / "raw").exists()
    assert (tmp_path / "payloads").exists()


def test_setup_is_idempotent(monkeypatch, tmp_path: Path):
    from config import settings

    monkeypatch.setattr(settings, "analytics_enabled", True)
    monkeypatch.setattr(settings, "analytics_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "")

    instrumentation.setup_observability()
    al1 = instrumentation.get_analytics_logger()
    instrumentation.setup_observability()  # 二度呼んでも OK
    al2 = instrumentation.get_analytics_logger()
    assert al1 is al2


async def test_shutdown_flushes_buffer(monkeypatch, tmp_path: Path):
    from config import settings

    monkeypatch.setattr(settings, "analytics_enabled", True)
    monkeypatch.setattr(settings, "analytics_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "")
    monkeypatch.setattr(settings, "analytics_service_name", "test-svc")
    # default min_age=30s だと shutdown 時の最終 upload で raw が pickup されない。
    # ここでは「flush だけは走る」ことを確認したいので raw に残っていれば OK とする。
    monkeypatch.setattr(settings, "analytics_uploader_min_age_seconds", 30.0)

    instrumentation.setup_observability()
    al = instrumentation.get_analytics_logger()
    al.emit(
        event_type="business_event",
        event_version="1.0.0",
        severity="INFO",
        fields={"business_domain": "test", "action": "x"},
    )
    assert al.buffer_size == 1
    await instrumentation.shutdown_observability()
    assert al.buffer_size == 0
    # min_age=30s なので JSONL は raw/ に残ったまま (upload は別テストで検証)
    raw_files = list((tmp_path / "raw").rglob("*.jsonl"))
    uploaded_files = list((tmp_path / "uploaded").rglob("*.jsonl"))
    assert raw_files or uploaded_files


# --------------------------------------------------------------------------
# Phase 5 Step 10: GCP backend 切替 + LocalUploader 連携
# --------------------------------------------------------------------------


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
    monkeypatch, tmp_path: Path, caplog
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
    # bucket が無いのでフォールバック
    assert isinstance(cr.writer, LocalFilePayloadWriter)


def test_setup_creates_uploader_when_analytics_enabled(monkeypatch, tmp_path: Path):
    """ANALYTICS_ENABLED=true なら LocalUploader が DI コンテナにある。"""
    from analytics_platform.uploader.local_uploader import LocalUploader
    from config import settings

    monkeypatch.setenv("ANALYTICS_STORAGE_BACKEND", "local")
    monkeypatch.setattr(settings, "analytics_enabled", True)
    monkeypatch.setattr(settings, "analytics_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", "")

    instrumentation.setup_observability()

    uploader = instrumentation.get_uploader()
    assert isinstance(uploader, LocalUploader)
    # raw / uploaded / dead_letter ディレクトリが作られている
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
    """`analytics_upload_interval_seconds <= 0` なら背景タスクを起動しない。"""
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
    monkeypatch.setattr(settings, "analytics_service_name", "test-svc")
    # 即時 upload (production の 30s ヒステリシスを無効化)
    monkeypatch.setattr(settings, "analytics_uploader_min_age_seconds", 0.0)

    instrumentation.setup_observability()
    al = instrumentation.get_analytics_logger()
    al.emit(
        event_type="business_event",
        event_version="1.0.0",
        severity="INFO",
        fields={"business_domain": "test", "action": "x"},
    )

    await instrumentation.shutdown_observability()

    # raw/ から uploaded/ に移動されている (LocalMoveTransport 経由)
    uploaded_files = list((tmp_path / "uploaded").rglob("*.jsonl"))
    raw_files = list((tmp_path / "raw").rglob("*.jsonl"))
    assert uploaded_files, "expected JSONL to be uploaded"
    assert not raw_files, "raw should be empty after final upload"
