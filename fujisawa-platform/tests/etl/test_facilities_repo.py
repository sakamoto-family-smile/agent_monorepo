"""FacilitiesRepo のテスト。

`facilities` テーブル (認可 + 認可外 = 約 160 件) は半年に 1 回しか更新しないため、
全削除 → 全 INSERT を **単一トランザクション** で実行する (proposal 0003 §4.5.5)。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from fujisawa_platform.etl._repos.facilities import (
    FacilitiesRepo,
    FacilityRecord,
)
from tests.etl._stubs import StubConnection, StubPool


def _record(
    *,
    facility_id: str = "fuji-001",
    name: str = "藤沢保育園",
    facility_type: str = "公立保育所",
    address: str = "藤沢市朝日町 1-1",
    phone: str | None = "0466-12-3456",
    capacity: int | None = 90,
    nearest_station: str | None = "藤沢駅",
    walk_minutes: int | None = 5,
    official_url: str | None = None,
    aliases: list[str] | None = None,
    lat: float | None = None,
    lng: float | None = None,
    source_url: str = "https://www.city.fujisawa.kanagawa.jp/.../ninka-ichiran.html",
    as_of: datetime | None = None,
) -> FacilityRecord:
    return FacilityRecord(
        facility_id=facility_id,
        name=name,
        facility_type=facility_type,
        address=address,
        phone=phone,
        capacity=capacity,
        nearest_station=nearest_station,
        walk_minutes=walk_minutes,
        official_url=official_url,
        aliases=aliases or [],
        lat=lat,
        lng=lng,
        source_url=source_url,
        as_of=as_of or datetime(2026, 5, 10, 0, 0, tzinfo=UTC),
    )


class _TxConnection(StubConnection):
    """`async with conn.transaction():` をサポートする拡張。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.tx_entered = 0
        self.tx_exited = 0

    def transaction(self) -> _TxConnection:
        return self

    async def __aenter__(self) -> _TxConnection:
        self.tx_entered += 1
        return self

    async def __aexit__(self, *args: Any) -> None:
        self.tx_exited += 1


class TestReplaceAll:
    @pytest.mark.asyncio
    async def test_deletes_then_inserts_in_single_transaction(self) -> None:
        conn = _TxConnection()
        repo = FacilitiesRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        await repo.replace_all([_record(facility_id="a"), _record(facility_id="b")])

        # transaction が 1 回張られていること
        assert conn.tx_entered == 1
        assert conn.tx_exited == 1

        # 1 つ目が DELETE、その後 INSERT 2 件
        assert len(conn.executed) == 3
        delete_sql, _ = conn.executed[0]
        assert delete_sql.strip().startswith("DELETE FROM facilities")
        assert all("INSERT INTO facilities" in sql for sql, _ in conn.executed[1:])

    @pytest.mark.asyncio
    async def test_inserts_all_columns_in_correct_order(self) -> None:
        conn = _TxConnection()
        repo = FacilitiesRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        record = _record(
            facility_id="fuji-001",
            aliases=["藤沢市立藤沢保育園", "藤沢ほいくえん"],
        )
        await repo.replace_all([record])

        _, insert_args = conn.executed[1]
        # 順序: facility_id, name, facility_type, address, phone, capacity,
        #       nearest_station, walk_minutes, official_url, aliases (json),
        #       lat, lng, source_url, as_of
        assert insert_args[0] == "fuji-001"
        assert insert_args[1] == "藤沢保育園"
        assert insert_args[2] == "公立保育所"
        assert insert_args[3] == "藤沢市朝日町 1-1"
        assert insert_args[4] == "0466-12-3456"
        assert insert_args[5] == 90
        assert insert_args[6] == "藤沢駅"
        assert insert_args[7] == 5
        # aliases は jsonb なので JSON 文字列で渡す想定
        assert insert_args[9] == '["藤沢市立藤沢保育園", "藤沢ほいくえん"]'

    @pytest.mark.asyncio
    async def test_empty_list_still_deletes(self) -> None:
        """0 件渡された場合でも DELETE は実行される (古いマスタを残さないため)。"""
        conn = _TxConnection()
        repo = FacilitiesRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        await repo.replace_all([])

        assert len(conn.executed) == 1
        sql, _ = conn.executed[0]
        assert sql.strip().startswith("DELETE FROM facilities")


class TestCount:
    @pytest.mark.asyncio
    async def test_returns_count(self) -> None:
        conn = StubConnection(fetchrow_results=[{"c": 128}])
        repo = FacilitiesRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        n = await repo.count()
        assert n == 128

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_row(self) -> None:
        conn = StubConnection(fetchrow_results=[None])
        repo = FacilitiesRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        n = await repo.count()
        assert n == 0


class TestFacilityRecordModel:
    def test_frozen(self) -> None:
        rec = _record()
        with pytest.raises(Exception):
            rec.name = "別名"  # type: ignore[misc]

    def test_aliases_default_empty_list(self) -> None:
        rec = FacilityRecord(
            facility_id="x",
            name="X",
            facility_type="公立保育所",
            address="住所",
            source_url="https://example.com",
            as_of=datetime(2026, 5, 10, tzinfo=UTC),
        )
        assert rec.aliases == []
