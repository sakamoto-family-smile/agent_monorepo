"""EtlRunsRepo のテスト。

ETL Job の `etl_runs` テーブルへの記録 (start/finish/status/source_hash) と
直近 N 件取得 (5 連敗判定用) を mock asyncpg.Pool で検証する。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from fujisawa_platform.etl._repos.etl_runs import EtlRunRecord, EtlRunsRepo
from tests.etl._stubs import StubConnection, StubPool


def _row(
    *,
    job_name: str = "weekly_crawl_etl",
    run_id: str = "weekly_crawl_etl-20260510-0300",
    status: str = "success",
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    source_url: str | None = None,
    source_hash: str | None = None,
    rows_written: int | None = 0,
    error_message: str | None = None,
) -> dict[str, Any]:
    return {
        "job_name": job_name,
        "run_id": run_id,
        "started_at": started_at or datetime(2026, 5, 10, 3, 0, tzinfo=UTC),
        "finished_at": finished_at,
        "status": status,
        "source_url": source_url,
        "source_hash": source_hash,
        "rows_written": rows_written,
        "error_message": error_message,
    }


class TestStartRun:
    @pytest.mark.asyncio
    async def test_inserts_with_running_status(self) -> None:
        conn = StubConnection()
        repo = EtlRunsRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        await repo.start_run(
            job_name="weekly_crawl_etl",
            run_id="weekly_crawl_etl-20260510-0300",
            started_at=datetime(2026, 5, 10, 3, 0, tzinfo=UTC),
            source_url="https://www.city.fujisawa.kanagawa.jp/sitemap.xml",
        )

        assert len(conn.executed) == 1
        sql, args = conn.executed[0]
        assert "INSERT INTO etl_runs" in sql
        assert "running" in args
        assert args[0] == "weekly_crawl_etl"
        assert args[1] == "weekly_crawl_etl-20260510-0300"


class TestFinishRun:
    @pytest.mark.asyncio
    async def test_updates_status_and_finished_at(self) -> None:
        conn = StubConnection()
        repo = EtlRunsRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        await repo.finish_run(
            job_name="weekly_crawl_etl",
            run_id="weekly_crawl_etl-20260510-0300",
            finished_at=datetime(2026, 5, 10, 4, 0, tzinfo=UTC),
            status="success",
            source_hash="a" * 64,
            rows_written=1100,
        )

        sql, args = conn.executed[0]
        assert "UPDATE etl_runs" in sql
        assert "SET" in sql
        # status, finished_at, source_hash, rows_written, error_message,
        # job_name, run_id (WHERE)
        assert "success" in args
        assert "a" * 64 in args
        assert 1100 in args

    @pytest.mark.asyncio
    async def test_failed_run_records_error_message(self) -> None:
        conn = StubConnection()
        repo = EtlRunsRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        await repo.finish_run(
            job_name="weekly_crawl_etl",
            run_id="weekly_crawl_etl-20260510-0300",
            finished_at=datetime(2026, 5, 10, 4, 0, tzinfo=UTC),
            status="failed",
            error_message="Cloud SQL connection lost",
        )

        _, args = conn.executed[0]
        assert "failed" in args
        assert "Cloud SQL connection lost" in args


class TestRecentRuns:
    @pytest.mark.asyncio
    async def test_returns_recent_records_in_order(self) -> None:
        rows = [
            _row(run_id="run-3", status="success"),
            _row(run_id="run-2", status="failed"),
            _row(run_id="run-1", status="success"),
        ]
        conn = StubConnection(fetch_results=[rows])
        repo = EtlRunsRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        recent = await repo.recent_runs("weekly_crawl_etl", limit=3)

        assert len(recent) == 3
        assert [r.run_id for r in recent] == ["run-3", "run-2", "run-1"]
        sql, args = conn.fetched[0]
        assert "ORDER BY started_at DESC" in sql
        assert args == ("weekly_crawl_etl", 3)

    @pytest.mark.asyncio
    async def test_returns_empty_for_first_time(self) -> None:
        conn = StubConnection(fetch_results=[[]])
        repo = EtlRunsRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        recent = await repo.recent_runs("monthly_vacancy_etl", limit=5)
        assert recent == []


class TestEtlRunRecordModel:
    def test_frozen(self) -> None:
        record = EtlRunRecord(
            job_name="weekly_crawl_etl",
            run_id="run-1",
            started_at=datetime(2026, 5, 10, 3, 0, tzinfo=UTC),
            finished_at=None,
            status="running",
            source_url=None,
            source_hash=None,
            rows_written=None,
            error_message=None,
        )
        with pytest.raises(Exception):
            record.status = "success"  # type: ignore[misc]
