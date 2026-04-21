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
    # ファイルが書かれているはず
    assert list((tmp_path / "raw").rglob("*.jsonl"))
