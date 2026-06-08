"""media 配信 backend (memory / gcs) の unit テスト (PROPOSAL-0011 P3-A)。"""

from __future__ import annotations

import pytest

import config
from services import media
from services.blob_store import get_report_store, reset_blob_stores


@pytest.fixture(autouse=True)
def _reset():
    reset_blob_stores()
    yield
    reset_blob_stores()


# ---------------------------------------------------------------------------
# memory backend
# ---------------------------------------------------------------------------


def test_memory_report_url_uses_public_base(monkeypatch):
    monkeypatch.setattr(config.settings, "media_backend", "memory")
    monkeypatch.setattr(config.settings, "public_base_url", "https://x.example")
    url = media.store_report_md("# hello")
    assert url is not None
    assert url.startswith("https://x.example/api/line/report/")
    assert url.endswith(".md")
    # store に実体が入っている
    rid = url.rsplit("/", 1)[-1][: -len(".md")]
    assert get_report_store().get(rid) is not None


def test_memory_image_url(monkeypatch):
    monkeypatch.setattr(config.settings, "media_backend", "memory")
    monkeypatch.setattr(config.settings, "public_base_url", "https://x.example")
    url = media.store_chart_png(b"\x89PNG")
    assert url.startswith("https://x.example/api/line/image/")
    assert url.endswith(".png")


def test_memory_no_base_returns_none(monkeypatch):
    monkeypatch.setattr(config.settings, "media_backend", "memory")
    monkeypatch.setattr(config.settings, "public_base_url", "")
    assert media.store_report_md("x") is None
    assert media.store_chart_png(b"x") is None


def test_empty_report_returns_none(monkeypatch):
    monkeypatch.setattr(config.settings, "media_backend", "memory")
    monkeypatch.setattr(config.settings, "public_base_url", "https://x.example")
    assert media.store_report_md("") is None


# ---------------------------------------------------------------------------
# gcs backend (storage.Client を fake に差し替え)
# ---------------------------------------------------------------------------


class _FakeBlob:
    def __init__(self):
        self.content_disposition = None
        self.uploaded = None

    def upload_from_string(self, data, content_type=None):
        self.uploaded = (data, content_type)


class _FakeBucket:
    def __init__(self):
        self.blobs = {}

    def blob(self, name):
        b = _FakeBlob()
        self.blobs[name] = b
        return b


class _FakeClient:
    def __init__(self):
        self._bucket = _FakeBucket()

    def bucket(self, name):
        return self._bucket


def test_gcs_image_url(monkeypatch):
    monkeypatch.setattr(config.settings, "media_backend", "gcs")
    monkeypatch.setattr(config.settings, "media_gcs_bucket", "media-bkt")
    monkeypatch.setattr(
        config.settings, "media_gcs_public_base", "https://storage.googleapis.com"
    )
    from google.cloud import storage

    monkeypatch.setattr(storage, "Client", _FakeClient)

    url = media.store_chart_png(b"PNGDATA")
    assert url.startswith("https://storage.googleapis.com/media-bkt/image/")
    assert url.endswith(".png")


def test_gcs_report_sets_attachment(monkeypatch):
    monkeypatch.setattr(config.settings, "media_backend", "gcs")
    monkeypatch.setattr(config.settings, "media_gcs_bucket", "media-bkt")
    from google.cloud import storage

    fake_client = _FakeClient()
    monkeypatch.setattr(storage, "Client", lambda: fake_client)

    url = media.store_report_md("# r")
    assert "/report/" in url and url.endswith(".md")
    blob = next(iter(fake_client._bucket.blobs.values()))
    assert blob.content_disposition.startswith("attachment;")


def test_gcs_no_bucket_returns_none(monkeypatch):
    monkeypatch.setattr(config.settings, "media_backend", "gcs")
    monkeypatch.setattr(config.settings, "media_gcs_bucket", "")
    assert media.store_chart_png(b"x") is None
