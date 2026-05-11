"""GcsArchive のテスト (google.cloud.storage を monkeypatch で mock)。

実 GCS 接続はせず、storage.Client / Bucket / Blob のメソッド呼び出しを記録する fake で
SQL 相当 (path / content / content_type / metadata) を検証する。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from fujisawa_platform.etl.pdf_archive import GcsArchive

_NOW = datetime(2026, 5, 11, 3, 0, tzinfo=UTC)


# ─────────────────────────────────────────────────────────────────────
# google.cloud.storage の最小 fake
# ─────────────────────────────────────────────────────────────────────


class _FakeBlob:
    def __init__(self, bucket: _FakeBucket, name: str) -> None:
        self._bucket = bucket
        self.name = name
        self.metadata: dict[str, str] | None = None
        self.content_type: str | None = None
        self.uploaded_bytes: bytes | None = None
        self._exists = False

    def upload_from_string(
        self,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> None:
        self.uploaded_bytes = data
        self.content_type = content_type
        self._exists = True
        self._bucket._blobs[self.name] = self

    def download_as_bytes(self) -> bytes:
        if self.uploaded_bytes is None:
            raise RuntimeError("blob has no content")
        return self.uploaded_bytes

    def exists(self) -> bool:
        return self._exists


class _FakeBucket:
    def __init__(self, name: str) -> None:
        self.name = name
        self._blobs: dict[str, _FakeBlob] = {}

    def blob(self, name: str) -> _FakeBlob:
        if name not in self._blobs:
            return _FakeBlob(self, name)
        return self._blobs[name]


class _FakeClient:
    def __init__(self) -> None:
        self._buckets: dict[str, _FakeBucket] = {}
        self.bucket_calls: list[str] = []

    def bucket(self, name: str) -> _FakeBucket:
        self.bucket_calls.append(name)
        if name not in self._buckets:
            self._buckets[name] = _FakeBucket(name)
        return self._buckets[name]


@pytest.fixture
def fake_gcs(monkeypatch: pytest.MonkeyPatch) -> _FakeClient:
    """`google.cloud.storage.Client` を fake に差し替え。"""
    client = _FakeClient()
    fake_module = type(
        "FakeStorageModule",
        (),
        {"Client": lambda: client},
    )

    import sys

    # google.cloud.storage を fake module で差し替え
    monkeypatch.setitem(sys.modules, "google.cloud.storage", fake_module)

    # google.cloud パッケージも fake で挿しておく
    fake_cloud = type("FakeGoogleCloud", (), {"storage": fake_module})
    fake_google = type("FakeGoogle", (), {"cloud": fake_cloud})
    monkeypatch.setitem(sys.modules, "google.cloud", fake_cloud)
    monkeypatch.setitem(sys.modules, "google", fake_google)
    return client


# ─────────────────────────────────────────────────────────────────────
# GcsArchive
# ─────────────────────────────────────────────────────────────────────


class TestPut:
    @pytest.mark.asyncio
    async def test_uploads_to_correct_bucket_and_blob(self, fake_gcs: _FakeClient) -> None:
        archive = GcsArchive(bucket_name="fujisawa-pdf-archive")
        result = await archive.put(
            path="biyearly_admission_etl/2026/1st/abc-r8.pdf",
            content=b"%PDF-fake",
            source_url="https://www.city.fujisawa.kanagawa.jp/r8.pdf",
            fetched_at=_NOW,
        )

        assert result.backend == "gcs"
        assert result.path == "biyearly_admission_etl/2026/1st/abc-r8.pdf"
        assert fake_gcs.bucket_calls[-1] == "fujisawa-pdf-archive"

        bucket = fake_gcs._buckets["fujisawa-pdf-archive"]
        blob = bucket._blobs["biyearly_admission_etl/2026/1st/abc-r8.pdf"]
        assert blob.uploaded_bytes == b"%PDF-fake"
        assert blob.content_type == "application/pdf"

    @pytest.mark.asyncio
    async def test_sets_metadata_with_source_url_and_fetched_at(
        self, fake_gcs: _FakeClient
    ) -> None:
        archive = GcsArchive(bucket_name="fujisawa-pdf-archive")
        await archive.put(
            path="x.pdf",
            content=b"x",
            source_url="https://example.com/x.pdf",
            fetched_at=_NOW,
        )

        bucket = fake_gcs._buckets["fujisawa-pdf-archive"]
        blob = bucket._blobs["x.pdf"]
        assert blob.metadata is not None
        assert blob.metadata["source_url"] == "https://example.com/x.pdf"
        assert blob.metadata["fetched_at"] == _NOW.isoformat()


class TestGet:
    @pytest.mark.asyncio
    async def test_returns_bytes(self, fake_gcs: _FakeClient) -> None:
        archive = GcsArchive(bucket_name="fujisawa-pdf-archive")
        await archive.put(
            path="x.pdf", content=b"hello", source_url="https://example.com/x.pdf", fetched_at=_NOW
        )

        content = await archive.get("x.pdf")
        assert content == b"hello"


class TestExists:
    @pytest.mark.asyncio
    async def test_returns_true_after_put(self, fake_gcs: _FakeClient) -> None:
        archive = GcsArchive(bucket_name="fujisawa-pdf-archive")
        await archive.put(
            path="x.pdf", content=b"x", source_url="https://example.com/x.pdf", fetched_at=_NOW
        )
        assert await archive.exists("x.pdf") is True

    @pytest.mark.asyncio
    async def test_returns_false_when_missing(self, fake_gcs: _FakeClient) -> None:
        archive = GcsArchive(bucket_name="fujisawa-pdf-archive")
        assert await archive.exists("missing.pdf") is False


class TestLazyImport:
    @pytest.mark.asyncio
    async def test_raises_when_google_cloud_storage_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`google-cloud-storage` 未インストール時は import 時に分かりやすいエラーを上げる。"""
        import builtins
        import sys

        # キャッシュされた google.cloud.storage が居たら退場させる
        for key in list(sys.modules.keys()):
            if key == "google.cloud.storage" or key.startswith("google.cloud.storage."):
                monkeypatch.delitem(sys.modules, key, raising=False)

        original_import = builtins.__import__

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "google.cloud.storage" or name.startswith("google.cloud.storage."):
                raise ImportError("google-cloud-storage not installed")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        archive = GcsArchive(bucket_name="fujisawa-pdf-archive")
        with pytest.raises(RuntimeError, match="google-cloud-storage"):
            await archive.put(
                path="x.pdf",
                content=b"x",
                source_url="https://example.com/x.pdf",
                fetched_at=_NOW,
            )
