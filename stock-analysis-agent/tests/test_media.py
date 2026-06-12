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
    assert media.store_report_html("") is None


def test_md_content_type_declares_utf8(monkeypatch):
    """LINE 内蔵ブラウザの文字化け対策: charset=utf-8 を明示する。"""
    monkeypatch.setattr(config.settings, "media_backend", "memory")
    monkeypatch.setattr(config.settings, "public_base_url", "https://x.example")
    url = media.store_report_md("# 日本語")
    rid = url.rsplit("/", 1)[-1][: -len(".md")]
    _, ctype = get_report_store().get(rid)
    assert ctype == "text/markdown; charset=utf-8"


def test_html_report_renders_markdown(monkeypatch):
    monkeypatch.setattr(config.settings, "media_backend", "memory")
    monkeypatch.setattr(config.settings, "public_base_url", "https://x.example")
    url = media.store_report_html("# 見出し\n\n| A | B |\n|---|---|\n| 1 | 2 |")
    assert url.endswith(".html")
    rid = url.rsplit("/", 1)[-1][: -len(".html")]
    data, ctype = get_report_store().get(rid)
    html = data.decode("utf-8")
    assert ctype == "text/html; charset=utf-8"
    assert '<meta charset="utf-8">' in html
    assert "<h1>見出し</h1>" in html
    assert "<table>" in html  # tables extension
    assert "投資勧誘" in html  # disclaimer footer


def test_html_falls_back_to_pre_on_conversion_error(monkeypatch):
    monkeypatch.setattr(config.settings, "media_backend", "memory")
    monkeypatch.setattr(config.settings, "public_base_url", "https://x.example")

    def boom(*a, **k):
        raise RuntimeError("converter broken")

    import markdown as md_lib

    monkeypatch.setattr(md_lib, "markdown", boom)
    url = media.store_report_html("# <script>alert(1)</script>")
    rid = url.rsplit("/", 1)[-1][: -len(".html")]
    data, _ = get_report_store().get(rid)
    html = data.decode("utf-8")
    assert "<pre" in html
    assert "&lt;script&gt;" in html  # escape されている


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


def test_gcs_html_is_inline_not_attachment(monkeypatch):
    """HTML はブラウザ表示 (inline) するため attachment を付けない。"""
    monkeypatch.setattr(config.settings, "media_backend", "gcs")
    monkeypatch.setattr(config.settings, "media_gcs_bucket", "media-bkt")
    from google.cloud import storage

    fake_client = _FakeClient()
    monkeypatch.setattr(storage, "Client", lambda: fake_client)

    url = media.store_report_html("# r")
    assert url.endswith(".html")
    blob = next(iter(fake_client._bucket.blobs.values()))
    assert blob.content_disposition is None
    assert blob.uploaded[1] == "text/html; charset=utf-8"


def test_gcs_no_bucket_returns_none(monkeypatch):
    monkeypatch.setattr(config.settings, "media_backend", "gcs")
    monkeypatch.setattr(config.settings, "media_gcs_bucket", "")
    assert media.store_chart_png(b"x") is None
