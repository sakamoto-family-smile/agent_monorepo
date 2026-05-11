"""AdmissionRepo のテスト。

`admission_results` テーブルへの UPSERT (by (facility_id, year, round, age_class)) を
mock asyncpg.Pool で検証する。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fujisawa_platform.etl._repos.admission import AdmissionRepo, AdmissionResultRecord
from tests.etl._stubs import StubConnection, StubPool


def _record(
    *,
    facility_id: str = "kouritsu-3a4b5c6d7e8f",
    year: int = 2026,
    round: str = "1st",
    age_class: int = 0,
    applicants_at_deadline: int | None = 30,
    capacity: int | None = 12,
    vacancy_after: int | None = 0,
    min_basic_score: int | None = None,
    min_priority: str | None = None,
    min_coordination_score: int | None = None,
    min_index_notation: str | None = None,
    source_pdf_url: str = "https://example.com/r8_admission_1st.pdf",
    as_of: datetime | None = None,
) -> AdmissionResultRecord:
    return AdmissionResultRecord(
        facility_id=facility_id,
        year=year,
        round=round,
        age_class=age_class,
        applicants_at_deadline=applicants_at_deadline,
        capacity=capacity,
        vacancy_after=vacancy_after,
        min_basic_score=min_basic_score,
        min_priority=min_priority,
        min_coordination_score=min_coordination_score,
        min_index_notation=min_index_notation,
        source_pdf_url=source_pdf_url,
        as_of=as_of or datetime(2026, 5, 11, 0, 0, tzinfo=UTC),
    )


class TestUpsertMany:
    @pytest.mark.asyncio
    async def test_upsert_one_per_record(self) -> None:
        conn = StubConnection()
        repo = AdmissionRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        await repo.upsert_many(
            [
                _record(age_class=0),
                _record(age_class=1, capacity=18, applicants_at_deadline=20),
            ]
        )

        assert len(conn.executed) == 2
        for sql, _ in conn.executed:
            assert "INSERT INTO admission_results" in sql
            assert "ON CONFLICT (facility_id, year, round, age_class) DO UPDATE" in sql

    @pytest.mark.asyncio
    async def test_passes_all_columns(self) -> None:
        conn = StubConnection()
        repo = AdmissionRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        rec = _record(
            facility_id="kouritsu-aaaabbbbcccc",
            year=2022,
            round="2nd",
            age_class=2,
            applicants_at_deadline=15,
            capacity=20,
            vacancy_after=5,
            min_basic_score=10,
            min_priority="F",
            min_coordination_score=11,
            min_index_notation="10F11※",
        )
        await repo.upsert_many([rec])

        _, args = conn.executed[0]
        # columns: facility_id, year, round, age_class, applicants_at_deadline,
        # capacity, vacancy_after, min_basic_score, min_priority,
        # min_coordination_score, min_index_notation, source_pdf_url, as_of,
        # schema_version
        assert args[0] == "kouritsu-aaaabbbbcccc"
        assert args[1] == 2022
        assert args[2] == "2nd"
        assert args[3] == 2
        assert args[4] == 15
        assert args[5] == 20
        assert args[6] == 5
        assert args[7] == 10
        assert args[8] == "F"
        assert args[9] == 11
        assert args[10] == "10F11※"

    @pytest.mark.asyncio
    async def test_empty_list_is_noop(self) -> None:
        conn = StubConnection()
        repo = AdmissionRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        n = await repo.upsert_many([])
        assert n == 0
        assert conn.executed == []

    @pytest.mark.asyncio
    async def test_returns_count(self) -> None:
        conn = StubConnection()
        repo = AdmissionRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        n = await repo.upsert_many([_record(), _record(age_class=1), _record(age_class=2)])
        assert n == 3


class TestCount:
    @pytest.mark.asyncio
    async def test_returns_count_filtered_by_year_round(self) -> None:
        conn = StubConnection(fetchrow_results=[{"c": 128}])
        repo = AdmissionRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        n = await repo.count(year=2026, round="1st")
        assert n == 128
        sql, args = conn.fetchrowed[0]
        assert "WHERE year = $1 AND round = $2" in sql
        assert args == (2026, "1st")

    @pytest.mark.asyncio
    async def test_returns_total_count_when_no_filter(self) -> None:
        conn = StubConnection(fetchrow_results=[{"c": 500}])
        repo = AdmissionRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        n = await repo.count()
        assert n == 500
        sql, args = conn.fetchrowed[0]
        assert "WHERE" not in sql
        assert args == ()


class TestRecordValidation:
    def test_round_must_be_1st_or_2nd(self) -> None:
        with pytest.raises(ValueError, match="round"):
            AdmissionResultRecord(
                facility_id="x",
                year=2026,
                round="3rd",
                age_class=0,
                source_pdf_url="https://example.com",
                as_of=datetime(2026, 5, 11, tzinfo=UTC),
            )

    def test_age_class_range_0_to_5(self) -> None:
        with pytest.raises(ValueError, match="age_class"):
            AdmissionResultRecord(
                facility_id="x",
                year=2026,
                round="1st",
                age_class=6,
                source_pdf_url="https://example.com",
                as_of=datetime(2026, 5, 11, tzinfo=UTC),
            )

    def test_frozen(self) -> None:
        rec = _record()
        with pytest.raises(Exception):
            rec.year = 2027  # type: ignore[misc]
