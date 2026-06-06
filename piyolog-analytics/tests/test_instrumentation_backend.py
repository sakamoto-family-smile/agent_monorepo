"""instrumentation の sink backend 選択テスト (PROPOSAL-0010 P5-3)。

analytics_storage_backend=pubsub + topic で PubSubSink、既定 local で
RotatingFileSink になることを確認する。
"""

from __future__ import annotations

from pathlib import Path

import config
import instrumentation.setup as setup_mod
from analytics_platform.observability.sinks.file_sink import RotatingFileSink
from analytics_platform.observability.sinks.pubsub_sink import PubSubSink


def _reset_module() -> None:
    setup_mod._initialized = False
    setup_mod._analytics_logger = None
    setup_mod._content_router = None
    setup_mod._tracer = None


def _common_settings(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config.settings, "analytics_enabled", True)
    monkeypatch.setattr(config.settings, "analytics_data_dir", str(tmp_path))
    monkeypatch.setattr(config.settings, "otel_exporter_otlp_endpoint", "")


def test_setup_uses_pubsub_sink_when_backend_pubsub(monkeypatch, tmp_path: Path) -> None:
    _common_settings(monkeypatch, tmp_path)
    monkeypatch.setattr(config.settings, "analytics_storage_backend", "pubsub")
    monkeypatch.setattr(config.settings, "analytics_pubsub_topic", "analytics-events")
    monkeypatch.setattr(config.settings, "analytics_gcp_project", "proj")
    _reset_module()
    try:
        setup_mod.setup_observability()
        assert isinstance(setup_mod.get_analytics_logger()._sink, PubSubSink)
    finally:
        _reset_module()


def test_setup_uses_local_sink_by_default(monkeypatch, tmp_path: Path) -> None:
    _common_settings(monkeypatch, tmp_path)
    monkeypatch.setattr(config.settings, "analytics_storage_backend", "local")
    monkeypatch.setattr(config.settings, "analytics_pubsub_topic", "")
    _reset_module()
    try:
        setup_mod.setup_observability()
        assert isinstance(setup_mod.get_analytics_logger()._sink, RotatingFileSink)
    finally:
        _reset_module()


def test_setup_falls_back_to_local_when_pubsub_topic_missing(
    monkeypatch, tmp_path: Path
) -> None:
    _common_settings(monkeypatch, tmp_path)
    monkeypatch.setattr(config.settings, "analytics_storage_backend", "pubsub")
    monkeypatch.setattr(config.settings, "analytics_pubsub_topic", "")  # 未設定
    _reset_module()
    try:
        setup_mod.setup_observability()
        assert isinstance(setup_mod.get_analytics_logger()._sink, RotatingFileSink)
    finally:
        _reset_module()
