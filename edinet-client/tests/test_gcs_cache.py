"""GcsCache のテスト (fake google.cloud.storage client で完結)。"""

from __future__ import annotations

from typing import Any

import pytest

from edinet_client import Cache, GcsCache


class _FakeBlob:
    """fake `storage.Blob`。 upload_from_string / download_as_bytes / exists を実装。"""

    def __init__(self, store: dict[str, bytes], key: str) -> None:
        self._store = store
        self._key = key
        self.uploads: list[tuple[bytes, str]] = []  # (payload, content_type)

    def exists(self) -> bool:
        return self._key in self._store

    def download_as_bytes(self) -> bytes:
        return self._store[self._key]

    def upload_from_string(self, payload: bytes, content_type: str = "") -> None:
        self._store[self._key] = payload
        self.uploads.append((payload, content_type))


class _FakeBucket:
    def __init__(self, name: str, store: dict[str, bytes]) -> None:
        self.name = name
        self._store = store
        self.blobs: list[_FakeBlob] = []

    def blob(self, key: str) -> _FakeBlob:
        b = _FakeBlob(self._store, key)
        self.blobs.append(b)
        return b


class _FakeClient:
    """fake `storage.Client`。"""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self._buckets: dict[str, _FakeBucket] = {}

    def bucket(self, name: str) -> _FakeBucket:
        if name not in self._buckets:
            self._buckets[name] = _FakeBucket(name, self.store)
        return self._buckets[name]


@pytest.fixture
def fake_client() -> _FakeClient:
    return _FakeClient()


@pytest.fixture
def cache(fake_client: _FakeClient) -> GcsCache:
    return GcsCache(bucket="test-bucket", prefix="edinet/", client=fake_client)


class TestProtocolConformance:
    def test_satisfies_cache_protocol(self, cache: GcsCache) -> None:
        cache_typed: Cache = cache  # type check (Protocol runtime_checkable)
        assert isinstance(cache_typed, Cache)


class TestPutGet:
    @pytest.mark.asyncio
    async def test_put_creates_object_with_key_layout(
        self, cache: GcsCache, fake_client: _FakeClient
    ) -> None:
        uri = await cache.put("S100ABC1", "pdf", b"%PDF-1.4 sample")

        assert uri == "gs://test-bucket/edinet/pdf/S100ABC1.pdf"
        assert fake_client.store["edinet/pdf/S100ABC1.pdf"] == b"%PDF-1.4 sample"

    @pytest.mark.asyncio
    async def test_put_uses_correct_mime_type(
        self, cache: GcsCache, fake_client: _FakeClient
    ) -> None:
        await cache.put("S100ABC1", "pdf", b"x")
        # 最後の upload の content_type を取り出して確認
        bucket = fake_client.bucket("test-bucket")
        last_blob = bucket.blobs[-1]
        assert last_blob.uploads[-1] == (b"x", "application/pdf")

    @pytest.mark.asyncio
    async def test_xbrl_zip_uses_zip_mime(
        self, cache: GcsCache, fake_client: _FakeClient
    ) -> None:
        await cache.put("S100ABC1", "xbrl_zip", b"PK\x03\x04")
        bucket = fake_client.bucket("test-bucket")
        last_blob = bucket.blobs[-1]
        assert last_blob.uploads[-1][1] == "application/zip"

    @pytest.mark.asyncio
    async def test_get_returns_payload(self, cache: GcsCache) -> None:
        await cache.put("S100ABC1", "pdf", b"fake content")
        result = await cache.get("S100ABC1", "pdf")
        assert result == b"fake content"

    @pytest.mark.asyncio
    async def test_get_miss_returns_none(self, cache: GcsCache) -> None:
        result = await cache.get("S100MISS", "pdf")
        assert result is None

    @pytest.mark.asyncio
    async def test_isolation_across_content_types(self, cache: GcsCache) -> None:
        await cache.put("S100ABC1", "pdf", b"pdf payload")
        await cache.put("S100ABC1", "xbrl_zip", b"xbrl payload")

        assert await cache.get("S100ABC1", "pdf") == b"pdf payload"
        assert await cache.get("S100ABC1", "xbrl_zip") == b"xbrl payload"


class TestPrefixNormalization:
    @pytest.mark.asyncio
    async def test_empty_prefix(self, fake_client: _FakeClient) -> None:
        cache = GcsCache(bucket="b", prefix="", client=fake_client)
        uri = await cache.put("S100ABC1", "pdf", b"x")
        assert uri == "gs://b/pdf/S100ABC1.pdf"

    @pytest.mark.asyncio
    async def test_leading_slash_stripped(self, fake_client: _FakeClient) -> None:
        cache = GcsCache(bucket="b", prefix="/foo/bar", client=fake_client)
        uri = await cache.put("S100ABC1", "pdf", b"x")
        assert uri == "gs://b/foo/bar/pdf/S100ABC1.pdf"

    @pytest.mark.asyncio
    async def test_trailing_slash_kept(self, fake_client: _FakeClient) -> None:
        cache = GcsCache(bucket="b", prefix="foo/bar/", client=fake_client)
        uri = await cache.put("S100ABC1", "pdf", b"x")
        assert uri == "gs://b/foo/bar/pdf/S100ABC1.pdf"

    @pytest.mark.asyncio
    async def test_nested_prefix(self, fake_client: _FakeClient) -> None:
        cache = GcsCache(
            bucket="b", prefix="env/prod/edinet/", client=fake_client
        )
        uri = await cache.put("S100ABC1", "xbrl_zip", b"x")
        assert uri == "gs://b/env/prod/edinet/xbrl_zip/S100ABC1.zip"


class TestInitValidation:
    def test_empty_bucket_rejected(self) -> None:
        with pytest.raises(ValueError, match="bucket"):
            GcsCache(bucket="", prefix="x/")

    def test_with_client_di(self) -> None:
        """client を DI すると lazy import が走らない。"""

        class _Stub:
            def bucket(self, name: str) -> Any:
                return None

        # 例外無しで生成できる
        cache = GcsCache(bucket="b", client=_Stub())
        assert cache is not None


class TestClientLazyImport:
    def test_missing_dep_raises_import_error_on_use(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """google-cloud-storage 未導入時、 操作した瞬間に ImportError。

        constructor は client=None でも通る (lazy import) が、 _ensure_bucket() で
        失敗するはず。 実環境では `[gcs]` extra をいれて回避する。
        """
        # client=None で構築 → 内部の lazy import を mock で ImportError 化
        cache = GcsCache(bucket="b", prefix="edinet/")

        import builtins

        real_import = builtins.__import__

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "google.cloud" or name.startswith("google.cloud"):
                raise ImportError("simulated missing google-cloud-storage")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        import asyncio

        with pytest.raises(ImportError, match="google-cloud-storage"):
            asyncio.run(cache.get("S100ABC1", "pdf"))
