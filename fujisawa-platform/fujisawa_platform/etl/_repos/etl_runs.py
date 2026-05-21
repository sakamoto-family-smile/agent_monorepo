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

    async def abort_stale_running(
        self,
        *,
        job_name: str,
        now: datetime,
        stale_after_hours: int = 4,
    ) -> int:
        """`running` のまま `stale_after_hours` 時間以上経過したレコードを
        `aborted` に reclassify する。

        Cloud Run task timeout で強制終了されたまま finish_run が呼ばれなかった
        orphan を、 次の Job 実行時に自動修復するための保険。 戻り値は更新された
        レコード数。

        実装注: 閾値は呼出側 (Python) で `now - timedelta(hours=N)` を計算して
        渡す。 PostgreSQL 側で `$1 - interval` を組み立てると、 asyncpg + PG の
        型推論で `$1` が `interval` と誤推論され `timestamptz < interval` の
        型ミスマッチが出る (2026-05-21 実 PG で検証)。
        """
        from datetime import timedelta

        cutoff = now - timedelta(hours=stale_after_hours)
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE etl_runs
                SET status = 'aborted',
                    finished_at = $1,
                    error_message = 'reclassified by abort_stale_running'
                WHERE job_name = $2
                  AND status = 'running'
                  AND started_at < $3
                """,
                now,
                job_name,
                cutoff,
            )
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0

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
