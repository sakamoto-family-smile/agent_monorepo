"""VacancyRepo + ApplicationRepo のテスト。

`vacancy_snapshots` / `application_snapshots` テーブルへの UPSERT
(by (facility_id, year_month, age_class)) を mock asyncpg.Pool で検証する。
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from fujisawa_platform.etl._repos.vacancy import (
    ApplicationRepo,
    ApplicationSnapshotRecord,
    VacancyRepo,
    VacancySnapshotRecord,
)
from tests.etl._stubs import StubConnection, StubPool

_NOW = datetime(2026, 5, 11, 0, 0, tzinfo=UTC)
_PDF_URL = "https://example.com/akizyoukyou20260401a.pdf"


def _vacancy(
    *,
    facility_id: str = "kouritsu-aaa",
    year_month: str = "2026-04",
    age_class: int = 0,
    vacancies: int = 0,
) -> VacancySnapshotRecord:
    return VacancySnapshotRecord(
        facility_id=facility_id,
        year_month=year_month,
        age_class=age_class,
        vacancies=vacancies,
        snapshot_date=date(2026, 4, 1),
        source_pdf_url=_PDF_URL,
        fetched_at=_NOW,
    )


def _application(
    *,
    facility_id: str = "kouritsu-aaa",
    year_month: str = "2026-04",
    age_class: int = 0,
    applicants: int = 0,
    capacity: int = 12,
) -> ApplicationSnapshotRecord:
    return ApplicationSnapshotRecord(
        facility_id=facility_id,
        year_month=year_month,
        age_class=age_class,
        applicants=applicants,
        capacity=capacity,
        snapshot_date=date(2026, 4, 1),
        source_pdf_url=_PDF_URL,
        fetched_at=_NOW,
    )


# ─────────────────────────────────────────────────────────────────────
# VacancyRepo
# ─────────────────────────────────────────────────────────────────────


class TestVacancyRepo:
    @pytest.mark.asyncio
    async def test_upsert_one_per_record(self) -> None:
        conn = StubConnection()
        repo = VacancyRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        await repo.upsert_many([_vacancy(age_class=0), _vacancy(age_class=1, vacancies=3)])

        assert len(conn.executed) == 2
        for sql, _ in conn.executed:
            assert "INSERT INTO vacancy_snapshots" in sql
            assert "ON CONFLICT (facility_id, year_month, age_class) DO UPDATE" in sql

    @pytest.mark.asyncio
    async def test_passes_all_columns(self) -> None:
        conn = StubConnection()
        repo = VacancyRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        rec = _vacancy(
            facility_id="kouritsu-abc",
            year_month="2026-04",
            age_class=2,
            vacancies=5,
        )
        await repo.upsert_many([rec])

        _, args = conn.executed[0]
        # facility_id, year_month, age_class, vacancies, snapshot_date,
        # source_pdf_url, fetched_at, schema_version
        assert args[0] == "kouritsu-abc"
        assert args[1] == "2026-04"
        assert args[2] == 2
        assert args[3] == 5
        assert args[4] == date(2026, 4, 1)
        assert args[5] == _PDF_URL
        assert args[6] == _NOW
        assert args[7] == "v1"

    @pytest.mark.asyncio
    async def test_empty_list_is_noop(self) -> None:
        conn = StubConnection()
        repo = VacancyRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        n = await repo.upsert_many([])
        assert n == 0
        assert conn.executed == []

    @pytest.mark.asyncio
    async def test_count_by_year_month(self) -> None:
        conn = StubConnection(fetchrow_results=[{"c": 128}])
        repo = VacancyRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        n = await repo.count(year_month="2026-04")
        assert n == 128
        sql, args = conn.fetchrowed[0]
        assert "WHERE year_month = $1" in sql
        assert args == ("2026-04",)


# ─────────────────────────────────────────────────────────────────────
# ApplicationRepo
# ─────────────────────────────────────────────────────────────────────


class TestApplicationRepo:
    @pytest.mark.asyncio
    async def test_upsert_one_per_record(self) -> None:
        conn = StubConnection()
        repo = ApplicationRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        await repo.upsert_many([_application(age_class=0), _application(age_class=1)])

        assert len(conn.executed) == 2
        for sql, _ in conn.executed:
            assert "INSERT INTO application_snapshots" in sql
            assert "ON CONFLICT (facility_id, year_month, age_class) DO UPDATE" in sql

    @pytest.mark.asyncio
    async def test_passes_all_columns(self) -> None:
        conn = StubConnection()
        repo = ApplicationRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        rec = _application(
            facility_id="kouritsu-xyz",
            year_month="2026-04",
            age_class=2,
            applicants=15,
            capacity=20,
        )
        await repo.upsert_many([rec])

        _, args = conn.executed[0]
        # facility_id, year_month, age_class, applicants, capacity,
        # snapshot_date, source_pdf_url, fetched_at, schema_version
        assert args[0] == "kouritsu-xyz"
        assert args[1] == "2026-04"
        assert args[2] == 2
        assert args[3] == 15
        assert args[4] == 20
        assert args[5] == date(2026, 4, 1)
        assert args[6] == _PDF_URL
        assert args[7] == _NOW

    @pytest.mark.asyncio
    async def test_count_returns_zero_when_no_row(self) -> None:
        conn = StubConnection(fetchrow_results=[None])
        repo = ApplicationRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        n = await repo.count()
        assert n == 0


# ─────────────────────────────────────────────────────────────────────
# Record validation
# ─────────────────────────────────────────────────────────────────────


class TestVacancySnapshotRecord:
    @pytest.mark.parametrize("bad", ["2026/04", "2026-4", "26-04", "2026-13"])
    def test_year_month_format(self, bad: str) -> None:
        with pytest.raises(ValueError, match="year_month"):
            VacancySnapshotRecord(
                facility_id="x",
                year_month=bad,
                age_class=0,
                vacancies=0,
                snapshot_date=date(2026, 4, 1),
                source_pdf_url=_PDF_URL,
                fetched_at=_NOW,
            )

    def test_age_class_range(self) -> None:
        with pytest.raises(ValueError, match="age_class"):
            VacancySnapshotRecord(
                facility_id="x",
                year_month="2026-04",
                age_class=6,
                vacancies=0,
                snapshot_date=date(2026, 4, 1),
                source_pdf_url=_PDF_URL,
                fetched_at=_NOW,
            )

    def test_negative_vacancies_rejected(self) -> None:
        with pytest.raises(ValueError, match="vacancies"):
            VacancySnapshotRecord(
                facility_id="x",
                year_month="2026-04",
                age_class=0,
                vacancies=-1,
                snapshot_date=date(2026, 4, 1),
                source_pdf_url=_PDF_URL,
                fetched_at=_NOW,
            )

    def test_frozen(self) -> None:
        rec = _vacancy()
        with pytest.raises(Exception):
            rec.vacancies = 99  # type: ignore[misc]


class TestApplicationSnapshotRecord:
    def test_capacity_non_negative(self) -> None:
        with pytest.raises(ValueError, match="capacity"):
            ApplicationSnapshotRecord(
                facility_id="x",
                year_month="2026-04",
                age_class=0,
                applicants=0,
                capacity=-1,
                snapshot_date=date(2026, 4, 1),
                source_pdf_url=_PDF_URL,
                fetched_at=_NOW,
            )

    def test_year_month_validation(self) -> None:
        with pytest.raises(ValueError, match="year_month"):
            ApplicationSnapshotRecord(
                facility_id="x",
                year_month="invalid",
                age_class=0,
                applicants=0,
                capacity=12,
                snapshot_date=date(2026, 4, 1),
                source_pdf_url=_PDF_URL,
                fetched_at=_NOW,
            )
