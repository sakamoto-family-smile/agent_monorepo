"""FacilitiesRepo のテスト。

`facilities` テーブル (認可 + 認可外 = 約 160 件) は半年に 1 回しか更新しないため、
UPSERT + 条件付き DELETE を **単一トランザクション** で実行する (proposal 0003 §4.5.5)。
旧実装は `DELETE FROM facilities` + 一括 INSERT だったが、 admission_results 等
下流テーブルが FK 参照を持つようになると DELETE が ForeignKeyViolationError で
fail するため、 UPSERT (`ON CONFLICT DO UPDATE`) + 「下流参照がない facility のみ
DELETE」 という設計に変更した。
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
    async def test_upserts_then_conditional_delete_in_single_transaction(self) -> None:
        conn = _TxConnection()
        repo = FacilitiesRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        await repo.replace_all([_record(facility_id="a"), _record(facility_id="b")])

        # transaction が 1 回張られていること
        assert conn.tx_entered == 1
        assert conn.tx_exited == 1

        # 順序: UPSERT × 2 → 条件付き DELETE × 1
        assert len(conn.executed) == 3
        for i in range(2):
            upsert_sql, _ = conn.executed[i]
            assert "INSERT INTO facilities" in upsert_sql
            assert "ON CONFLICT (facility_id) DO UPDATE" in upsert_sql
        delete_sql, delete_args = conn.executed[2]
        assert "DELETE FROM facilities" in delete_sql
        assert "NOT EXISTS" in delete_sql
        assert "admission_results" in delete_sql
        # incoming_ids が DELETE に渡されている
        assert delete_args == (["a", "b"],)

    @pytest.mark.asyncio
    async def test_upsert_uses_excluded_for_aliases_and_other_fields(self) -> None:
        conn = _TxConnection()
        repo = FacilitiesRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        record = _record(
            facility_id="fuji-001",
            aliases=["藤沢市立藤沢保育園", "藤沢ほいくえん"],
        )
        await repo.replace_all([record])

        upsert_sql, upsert_args = conn.executed[0]
        # UPSERT の DO UPDATE 節で EXCLUDED.aliases を採用していること
        assert "aliases = EXCLUDED.aliases" in upsert_sql
        # 引数順は INSERT のプレースホルダと一致:
        # facility_id, name, facility_type, address, phone, capacity,
        # nearest_station, walk_minutes, official_url, aliases (json),
        # lat, lng, source_url, as_of, schema_version
        assert upsert_args[0] == "fuji-001"
        assert upsert_args[1] == "藤沢保育園"
        assert upsert_args[2] == "公立保育所"
        assert upsert_args[3] == "藤沢市朝日町 1-1"
        assert upsert_args[4] == "0466-12-3456"
        assert upsert_args[5] == 90
        assert upsert_args[6] == "藤沢駅"
        assert upsert_args[7] == 5
        # aliases は jsonb なので JSON 文字列で渡す
        assert upsert_args[9] == '["藤沢市立藤沢保育園", "藤沢ほいくえん"]'

    @pytest.mark.asyncio
    async def test_empty_list_runs_conditional_delete_only(self) -> None:
        """0 件渡された場合 UPSERT は走らず、 下流参照の無い facility だけ DELETE される。"""
        conn = _TxConnection()
        repo = FacilitiesRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        await repo.replace_all([])

        assert len(conn.executed) == 1
        sql, args = conn.executed[0]
        assert "DELETE FROM facilities" in sql
        assert "NOT EXISTS" in sql
        # incoming_ids が空のままで渡されている (= 全 facility が候補だが FK 参照は除外)
        assert args == ([],)

    @pytest.mark.asyncio
    async def test_does_not_delete_facilities_referenced_by_downstream(self) -> None:
        """`DELETE WHERE NOT EXISTS (...)` の文面で下流 4 テーブルを除外していること。"""
        conn = _TxConnection()
        repo = FacilitiesRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        await repo.replace_all([_record(facility_id="a")])

        delete_sql, _ = conn.executed[1]
        for downstream in (
            "admission_results",
            "vacancy_snapshots",
            "application_snapshots",
            "competition_stats",
        ):
            assert downstream in delete_sql, (
                f"DELETE should preserve facilities referenced by {downstream}"
            )


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
