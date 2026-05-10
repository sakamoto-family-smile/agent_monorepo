"""EtlRunsRepo: `etl_runs` テーブル (proposal 0003 §4.5.6 / init_schema.sql §etl_runs) への薄い CRUD。

各 ETL Job は `run_etl_job` ラッパー経由で start_run / finish_run を呼び、
`recent_runs` で 5 連敗判定 (fail-fast 条件) を確認する。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:  # pragma: no cover
    import asyncpg


class EtlRunRecord(BaseModel):
    """`etl_runs` テーブルの 1 行。"""

    model_config = ConfigDict(frozen=True)

    job_name: str
    run_id: str
    started_at: datetime
    finished_at: datetime | None
    status: str  # 'running' | 'success' | 'failed' | 'skipped_unchanged'
    source_url: str | None
    source_hash: str | None
    rows_written: int | None
    error_message: str | None


class EtlRunsRepo:
    """`etl_runs` テーブルへのアクセス Repository。"""

    def __init__(self, *, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def start_run(
        self,
        *,
        job_name: str,
        run_id: str,
        started_at: datetime,
        source_url: str | None = None,
    ) -> None:
        """Job 実行開始時に行を INSERT する (status='running')。"""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO etl_runs (
                    job_name, run_id, started_at, status, source_url
                ) VALUES ($1, $2, $3, $4, $5)
                """,
                job_name,
                run_id,
                started_at,
                "running",
                source_url,
            )

    async def finish_run(
        self,
        *,
        job_name: str,
        run_id: str,
        finished_at: datetime,
        status: str,
        source_hash: str | None = None,
        rows_written: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """Job 実行終了時に status / finished_at を UPDATE する。"""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE etl_runs
                SET status = $1,
                    finished_at = $2,
                    source_hash = $3,
                    rows_written = $4,
                    error_message = $5
                WHERE job_name = $6 AND run_id = $7
                """,
                status,
                finished_at,
                source_hash,
                rows_written,
                error_message,
                job_name,
                run_id,
            )

    async def recent_runs(self, job_name: str, *, limit: int = 5) -> list[EtlRunRecord]:
        """直近 N 件の実行履歴を取得 (started_at 降順)。

        5 連敗 fail-fast 判定 (proposal 0003 §4.5.6) で利用する。
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    job_name, run_id, started_at, finished_at, status,
                    source_url, source_hash, rows_written, error_message
                FROM etl_runs
                WHERE job_name = $1
                ORDER BY started_at DESC
                LIMIT $2
                """,
                job_name,
                limit,
            )
        return [_row_to_record(r) for r in rows]


def _row_to_record(row: Any) -> EtlRunRecord:
    return EtlRunRecord(
        job_name=row["job_name"],
        run_id=row["run_id"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        status=row["status"],
        source_url=row["source_url"],
        source_hash=row["source_hash"],
        rows_written=row["rows_written"],
        error_message=row["error_message"],
    )


__all__ = ["EtlRunRecord", "EtlRunsRepo"]
