"""Cache 実装のテスト (LocalCache / InMemoryCache)。"""

from __future__ import annotations

from pathlib import Path

import pytest

from edinet_client import Cache, InMemoryCache, LocalCache


class TestInMemoryCache:
    @pytest.mark.asyncio
    async def test_put_then_get_roundtrip(self) -> None:
        cache = InMemoryCache()
        uri = await cache.put("S100ABC1", "pdf", b"fake pdf bytes")
        assert uri.startswith("memory://")

        retrieved = await cache.get("S100ABC1", "pdf")
        assert retrieved == b"fake pdf bytes"

    @pytest.mark.asyncio
    async def test_miss_returns_none(self) -> None:
        cache = InMemoryCache()
        assert await cache.get("S100MISS", "pdf") is None

    @pytest.mark.asyncio
    async def test_different_content_types_isolated(self) -> None:
        cache = InMemoryCache()
        await cache.put("S100ABC1", "pdf", b"pdf payload")
        await cache.put("S100ABC1", "xbrl_zip", b"xbrl payload")

        assert await cache.get("S100ABC1", "pdf") == b"pdf payload"
        assert await cache.get("S100ABC1", "xbrl_zip") == b"xbrl payload"


class TestLocalCache:
    @pytest.mark.asyncio
    async def test_put_creates_file_with_extension(self, tmp_path: Path) -> None:
        cache = LocalCache(root=tmp_path)
        uri = await cache.put("S100ABC1", "pdf", b"fake pdf bytes")

        expected_path = tmp_path / "pdf" / "S100ABC1.pdf"
        assert expected_path.exists()
        assert expected_path.read_bytes() == b"fake pdf bytes"
        assert uri.startswith("file://")
        assert uri.endswith("S100ABC1.pdf")

    @pytest.mark.asyncio
    async def test_get_returns_payload(self, tmp_path: Path) -> None:
        cache = LocalCache(root=tmp_path)
        await cache.put("S100DEF2", "xbrl_zip", b"PK fake zip")
        result = await cache.get("S100DEF2", "xbrl_zip")
        assert result == b"PK fake zip"

    @pytest.mark.asyncio
    async def test_miss_returns_none(self, tmp_path: Path) -> None:
        cache = LocalCache(root=tmp_path)
        assert await cache.get("S100MISS", "pdf") is None

    @pytest.mark.asyncio
    async def test_root_directory_auto_created(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "nested" / "edinet"
        assert not nested.exists()
        LocalCache(root=nested)
        assert nested.exists()

    @pytest.mark.asyncio
    async def test_isolation_across_content_types(self, tmp_path: Path) -> None:
        cache = LocalCache(root=tmp_path)
        await cache.put("S100ABC1", "pdf", b"pdf only")
        await cache.put("S100ABC1", "attach_zip", b"attach only")

        # 別 subdir に格納されるので衝突しない
        assert (tmp_path / "pdf" / "S100ABC1.pdf").exists()
        assert (tmp_path / "attach_zip" / "S100ABC1.zip").exists()


class TestCacheProtocol:
    def test_local_cache_satisfies_protocol(self, tmp_path: Path) -> None:
        cache: Cache = LocalCache(root=tmp_path)
        assert isinstance(cache, Cache)

    def test_in_memory_cache_satisfies_protocol(self) -> None:
        cache: Cache = InMemoryCache()
        assert isinstance(cache, Cache)
