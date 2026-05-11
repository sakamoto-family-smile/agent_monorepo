"""FacilitiesRepo.list_all + build_facility_resolver の追加テスト。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fujisawa_platform.etl._repos.facilities import FacilitiesRepo
from fujisawa_platform.etl.facility_resolver_builder import build_facility_resolver
from fujisawa_platform.resolver import FacilityResolver
from tests.etl._stubs import StubConnection, StubPool


def _row(
    *,
    facility_id: str = "kouritsu-aaa",
    name: str = "藤沢保育園",
    aliases: object = "[]",
) -> dict[str, object]:
    return {
        "facility_id": facility_id,
        "name": name,
        "facility_type": "公立保育所",
        "address": "藤沢市朝日町 1-1",
        "phone": "0466-12-3456",
        "capacity": 90,
        "nearest_station": None,
        "walk_minutes": None,
        "official_url": None,
        "aliases": aliases,
        "lat": None,
        "lng": None,
        "source_url": "https://www.city.fujisawa.kanagawa.jp/.../ninka.html",
        "as_of": datetime(2026, 5, 1, tzinfo=UTC),
        "schema_version": "v1",
    }


class TestListAll:
    @pytest.mark.asyncio
    async def test_returns_records(self) -> None:
        conn = StubConnection(
            fetch_results=[
                [
                    _row(facility_id="a", name="藤沢保育園"),
                    _row(facility_id="b", name="辻堂保育園"),
                ]
            ]
        )
        repo = FacilitiesRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        records = await repo.list_all()
        assert len(records) == 2
        assert records[0].facility_id == "a"
        assert records[1].name == "辻堂保育園"

    @pytest.mark.asyncio
    async def test_parses_aliases_jsonb_string(self) -> None:
        """JSONB は asyncpg 経由で str / list どちらでも入ってくる可能性がある。"""
        conn = StubConnection(
            fetch_results=[[_row(aliases='["市立藤沢保育園", "藤沢ほいくえん"]')]]
        )
        repo = FacilitiesRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        records = await repo.list_all()
        assert records[0].aliases == ["市立藤沢保育園", "藤沢ほいくえん"]

    @pytest.mark.asyncio
    async def test_handles_aliases_list_directly(self) -> None:
        conn = StubConnection(fetch_results=[[_row(aliases=["X", "Y"])]])
        repo = FacilitiesRepo(pool=StubPool(conn))  # type: ignore[arg-type]
        records = await repo.list_all()
        assert records[0].aliases == ["X", "Y"]

    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self) -> None:
        conn = StubConnection(fetch_results=[[]])
        repo = FacilitiesRepo(pool=StubPool(conn))  # type: ignore[arg-type]
        records = await repo.list_all()
        assert records == []


class TestBuildFacilityResolver:
    @pytest.mark.asyncio
    async def test_creates_resolver_from_repo(self) -> None:
        conn = StubConnection(
            fetch_results=[
                [
                    _row(facility_id="a", name="藤沢保育園", aliases='["市立藤沢保育園"]'),
                    _row(facility_id="b", name="辻堂保育園", aliases="[]"),
                ]
            ]
        )
        repo = FacilitiesRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        resolver = await build_facility_resolver(repo)

        assert isinstance(resolver, FacilityResolver)
        # canonical_name の完全一致
        hit = resolver.resolve("藤沢保育園")
        assert hit.facility_id == "a"
        # alias 完全一致
        hit = resolver.resolve("市立藤沢保育園")
        assert hit.facility_id == "a"
