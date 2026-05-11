"""AdmissionRepo.list_recent_years のテスト (Phase 4-2f stats compute 用)。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from fujisawa_platform.etl._repos.admission import AdmissionRepo
from tests.etl._stubs import StubConnection, StubPool


def _row(
    *,
    facility_id: str = "kouritsu-aaa",
    year: int = 2026,
    round: str = "1st",
    age_class: int = 0,
    applicants_at_deadline: int | None = 30,
    capacity: int | None = 12,
    vacancy_after: int | None = 0,
    source_pdf_url: str = "https://example.com/r.pdf",
) -> dict[str, Any]:
    return {
        "facility_id": facility_id,
        "year": year,
        "round": round,
        "age_class": age_class,
        "applicants_at_deadline": applicants_at_deadline,
        "capacity": capacity,
        "vacancy_after": vacancy_after,
        "min_basic_score": None,
        "min_priority": None,
        "min_coordination_score": None,
        "min_index_notation": None,
        "source_pdf_url": source_pdf_url,
        "as_of": datetime(2026, 5, 12, tzinfo=UTC),
        "schema_version": "v1",
    }


class TestListRecentYears:
    @pytest.mark.asyncio
    async def test_returns_records_filtered_by_year_range(self) -> None:
        rows = [
            _row(year=2024, applicants_at_deadline=24),
            _row(year=2025, applicants_at_deadline=18),
            _row(year=2026, applicants_at_deadline=12),
        ]
        conn = StubConnection(fetch_results=[rows])
        repo = AdmissionRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        records = await repo.list_recent_years(min_year=2024, max_year=2026)

        assert len(records) == 3
        sql, args = conn.fetched[0]
        assert "WHERE year BETWEEN $1 AND $2" in sql
        assert args == (2024, 2026)
        assert records[0].year == 2024
        assert records[2].applicants_at_deadline == 12

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_data(self) -> None:
        conn = StubConnection(fetch_results=[[]])
        repo = AdmissionRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        records = await repo.list_recent_years(min_year=2020, max_year=2026)
        assert records == []

    @pytest.mark.asyncio
    async def test_orders_by_facility_age_year(self) -> None:
        """ORDER BY 句は (facility_id, age_class, year) で安定ソート。"""
        conn = StubConnection(fetch_results=[[]])
        repo = AdmissionRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        await repo.list_recent_years(min_year=2024, max_year=2026)

        sql, _ = conn.fetched[0]
        assert "ORDER BY facility_id, age_class, year" in sql
