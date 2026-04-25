"""env 駆動の `gcp_config` ヘルパテスト。"""
from __future__ import annotations

import pytest

from analytics_platform import gcp_config
from analytics_platform.observability.content import LocalFilePayloadWriter


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in (
        "ANALYTICS_STORAGE_BACKEND",
        "ANALYTICS_GCS_BUCKET",
        "ANALYTICS_GCS_RAW_PREFIX",
        "ANALYTICS_GCS_PAYLOAD_PREFIX",
        "ANALYTICS_GCP_PROJECT",
    ):
        monkeypatch.delenv(k, raising=False)


def test_default_backend_is_local(monkeypatch):
    assert gcp_config.detect_storage_backend() == "local"
    assert gcp_config.load_gcs_config() is None


def test_gcs_backend_without_bucket_falls_back(monkeypatch):
    monkeypatch.setenv("ANALYTICS_STORAGE_BACKEND", "gcs")
    assert gcp_config.load_gcs_config() is None


def test_gcs_backend_with_bucket(monkeypatch):
    monkeypatch.setenv("ANALYTICS_STORAGE_BACKEND", "gcs")
    monkeypatch.setenv("ANALYTICS_GCS_BUCKET", "youyaku-ai-analytics")
    monkeypatch.setenv("ANALYTICS_GCP_PROJECT", "youyaku-ai")
    cfg = gcp_config.load_gcs_config()
    assert cfg is not None
    assert cfg.bucket_name == "youyaku-ai-analytics"
    assert cfg.project_id == "youyaku-ai"
    assert cfg.raw_prefix == "uploaded/"
    assert cfg.payload_prefix == "payloads/"


def test_custom_prefixes(monkeypatch):
    monkeypatch.setenv("ANALYTICS_STORAGE_BACKEND", "gcs")
    monkeypatch.setenv("ANALYTICS_GCS_BUCKET", "b")
    monkeypatch.setenv("ANALYTICS_GCS_RAW_PREFIX", "custom_raw/")
    monkeypatch.setenv("ANALYTICS_GCS_PAYLOAD_PREFIX", "custom_payloads/")
    cfg = gcp_config.load_gcs_config()
    assert cfg.raw_prefix == "custom_raw/"
    assert cfg.payload_prefix == "custom_payloads/"


def test_build_payload_writer_returns_local_by_default(tmp_path):
    writer = gcp_config.build_payload_writer(local_root=tmp_path)
    assert isinstance(writer, LocalFilePayloadWriter)


def test_build_payload_writer_returns_gcs_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_STORAGE_BACKEND", "gcs")
    monkeypatch.setenv("ANALYTICS_GCS_BUCKET", "b")
    writer = gcp_config.build_payload_writer(local_root=tmp_path)
    # lazy import 経由で GCSPayloadWriter が返る
    from analytics_platform.observability.content_gcs import GCSPayloadWriter

    assert isinstance(writer, GCSPayloadWriter)


def test_build_upload_transport_returns_local_by_default(tmp_path):
    transport = gcp_config.build_upload_transport(raw_root=tmp_path)
    from analytics_platform.uploader.local_uploader import LocalMoveTransport

    assert isinstance(transport, LocalMoveTransport)


def test_build_upload_transport_returns_gcs_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_STORAGE_BACKEND", "gcs")
    monkeypatch.setenv("ANALYTICS_GCS_BUCKET", "b")
    transport = gcp_config.build_upload_transport(raw_root=tmp_path)
    from analytics_platform.uploader.gcs_transport import GCSTransport

    assert isinstance(transport, GCSTransport)


def test_bucket_stripping_whitespace(monkeypatch):
    monkeypatch.setenv("ANALYTICS_STORAGE_BACKEND", "gcs")
    monkeypatch.setenv("ANALYTICS_GCS_BUCKET", "   ")
    assert gcp_config.load_gcs_config() is None
