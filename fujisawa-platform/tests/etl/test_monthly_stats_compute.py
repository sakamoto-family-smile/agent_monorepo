"""monthly_stats_compute_etl のテスト。

外部 fetch なし。admission_results を読み出して集計 → competition_stats に upsert する。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from fujisawa_platform.etl._repos.admission import AdmissionResultRecord
from fujisawa_platform.etl._repos.competition_stats import CompetitionStatsRecord
from fujisawa_platform.etl._runner import EtlRunResult
from fujisawa_platform.etl.monthly_stats_compute import (
    StatsComputeOutcome,
    compute_stats,
    run_monthly_stats_compute,
)

_NOW = datetime(2026, 5, 12, 0, 0, tzinfo=UTC)


def _admission(
    *,
    facility_id: str,
    year: int,
    age_class: int = 0,
    applicants_at_deadline: int = 30,
    capacity: int = 12,
) -> AdmissionResultRecord:
    return AdmissionResultRecord(
        facility_id=facility_id,
        year=year,
        round="1st",
        age_class=age_class,
        applicants_at_deadline=applicants_at_deadline,
        capacity=capacity,
        vacancy_after=0,
        source_pdf_url=f"https://example.com/{year}.pdf",
        as_of=_NOW,
    )


class _RecordingAdmissionRepo:
    def __init__(self, records: list[AdmissionResultRecord]) -> None:
        self._records = records

    async def list_recent_years(
        self, *, min_year: int, max_year: int
    ) -> list[AdmissionResultRecord]:
        return [r for r in self._records if min_year <= r.year <= max_year]


class _RecordingStatsRepo:
    def __init__(self) -> None:
        self.upserts: list[list[CompetitionStatsRecord]] = []

    async def upsert_many(self, records: list[CompetitionStatsRecord]) -> int:
        self.upserts.append(list(records))
        return len(records)


class _FakeRunsRepo:
    def __init__(self) -> None:
        self.starts: list[dict[str, Any]] = []
        self.finishes: list[dict[str, Any]] = []

    async def start_run(self, **kwargs: Any) -> None:
        self.starts.append(kwargs)

    async def finish_run(self, **kwargs: Any) -> None:
        self.finishes.append(kwargs)

    async def recent_runs(self, job_name: str, *, limit: int = 5) -> list[Any]:
        return []


# ─────────────────────────────────────────────────────────────────────
# compute_stats (DB 読み取り + 集計 + upsert)
# ─────────────────────────────────────────────────────────────────────


class TestComputeStats:
    @pytest.mark.asyncio
    async def test_computes_one_record_per_facility_and_age_class(self) -> None:
        records = [
            _admission(facility_id="kouritsu-aaa", age_class=0, year=2024),
            _admission(facility_id="kouritsu-aaa", age_class=0, year=2025),
            _admission(facility_id="kouritsu-aaa", age_class=1, year=2025),
            _admission(facility_id="kouritsu-bbb", age_class=0, year=2025),
        ]
        admission_repo = _RecordingAdmissionRepo(records)
        stats_repo = _RecordingStatsRepo()

        outcome = await compute_stats(
            admission_repo=admission_repo,  # type: ignore[arg-type]
            stats_repo=stats_repo,  # type: ignore[arg-type]
            current_year=2026,
            now=lambda: _NOW,
        )

        # 3 個の (facility_id, age_class) 組合せ
        assert outcome.rows_written == 3
        upserted = stats_repo.upserts[0]
        keys = {(r.facility_id, r.age_class) for r in upserted}
        assert keys == {
            ("kouritsu-aaa", 0),
            ("kouritsu-aaa", 1),
            ("kouritsu-bbb", 0),
        }

    @pytest.mark.asyncio
    async def test_reads_past_3_years(self) -> None:
        """current_year=2026 なら 2024..2026 の 3 年を読む。"""
        admission_repo = _RecordingAdmissionRepo([])
        stats_repo = _RecordingStatsRepo()

        called: dict[str, int] = {}

        async def list_recent_years(*, min_year: int, max_year: int) -> list[AdmissionResultRecord]:
            called["min"] = min_year
            called["max"] = max_year
            return []

        admission_repo.list_recent_years = list_recent_years  # type: ignore[method-assign]

        await compute_stats(
            admission_repo=admission_repo,  # type: ignore[arg-type]
            stats_repo=stats_repo,  # type: ignore[arg-type]
            current_year=2026,
            now=lambda: _NOW,
        )
        assert called["min"] == 2024
        assert called["max"] == 2026

    @pytest.mark.asyncio
    async def test_empty_admission_data_no_upsert(self) -> None:
        admission_repo = _RecordingAdmissionRepo([])
        stats_repo = _RecordingStatsRepo()

        outcome = await compute_stats(
            admission_repo=admission_repo,  # type: ignore[arg-type]
            stats_repo=stats_repo,  # type: ignore[arg-type]
            current_year=2026,
            now=lambda: _NOW,
        )
        assert outcome.rows_written == 0
        assert stats_repo.upserts == []

    @pytest.mark.asyncio
    async def test_dry_run_does_not_upsert(self) -> None:
        records = [_admission(facility_id="kouritsu-aaa", year=2025)]
        admission_repo = _RecordingAdmissionRepo(records)
        stats_repo = _RecordingStatsRepo()

        outcome = await compute_stats(
            admission_repo=admission_repo,  # type: ignore[arg-type]
            stats_repo=stats_repo,  # type: ignore[arg-type]
            current_year=2026,
            now=lambda: _NOW,
            dry_run=True,
        )
        # parse 結果はカウントされるが repo は呼ばれない
        assert outcome.rows_written == 1
        assert stats_repo.upserts == []


# ─────────────────────────────────────────────────────────────────────
# run_monthly_stats_compute (Cloud Run Job entrypoint)
# ─────────────────────────────────────────────────────────────────────


class TestRunMonthlyStatsCompute:
    @pytest.mark.asyncio
    async def test_returns_success_result(self) -> None:
        records = [
            _admission(facility_id="kouritsu-aaa", year=2025),
            _admission(facility_id="kouritsu-aaa", year=2026),
        ]
        runs = _FakeRunsRepo()

        result = await run_monthly_stats_compute(
            admission_repo=_RecordingAdmissionRepo(records),  # type: ignore[arg-type]
            stats_repo=_RecordingStatsRepo(),  # type: ignore[arg-type]
            runs_repo=runs,  # type: ignore[arg-type]
            run_id="monthly_stats_compute-20260523-0300",
            current_year=2026,
            now=lambda: _NOW,
        )

        assert isinstance(result, EtlRunResult)
        assert result.status == "success"
        assert result.rows_written == 1  # 1 施設 × 1 age_class
        assert runs.finishes[0]["status"] == "success"


class TestOutcomeModel:
    def test_frozen(self) -> None:
        outcome = StatsComputeOutcome(rows_written=10, facilities_processed=5)
        with pytest.raises(Exception):
            outcome.rows_written = 99  # type: ignore[misc]
