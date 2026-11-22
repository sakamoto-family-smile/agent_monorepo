"""アプリ内のジョブキュー (golf.db の jobs テーブル)。

同じ kind + ref_id のジョブは 1 件だけ。失敗したら指数バックオフで再試行し、
回数を使い切ったら failed にして残す (last_error を見て手で再実行できる)。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.storage.tables import jobs
from app.timeutil import iso

MAX_ATTEMPTS = 8
BACKOFF_BASE_SECONDS = 30
BACKOFF_MAX_SECONDS = 3600


@dataclass(frozen=True)
class Job:
    id: int
    kind: str
    ref_id: int
    attempts: int
    polls: int


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(BACKOFF_BASE_SECONDS * 2 ** max(attempts - 1, 0), BACKOFF_MAX_SECONDS))


async def enqueue(conn: AsyncConnection, kind: str, ref_id: int, now: datetime) -> None:
    await conn.execute(
        insert(jobs)
        .values(
            kind=kind,
            ref_id=ref_id,
            status="pending",
            attempts=0,
            polls=0,
            next_run_at=iso(now),
            created_at=iso(now),
            updated_at=iso(now),
        )
        .on_conflict_do_nothing(index_elements=["kind", "ref_id"])
    )


async def claim_due(conn: AsyncConnection, now: datetime, limit: int = 5) -> list[Job]:
    rows = (
        await conn.execute(
            sa.select(jobs)
            .where(jobs.c.status == "pending", jobs.c.next_run_at <= iso(now))
            .order_by(jobs.c.next_run_at, jobs.c.id)
            .limit(limit)
        )
    ).all()
    if rows:
        await conn.execute(
            sa.update(jobs)
            .where(jobs.c.id.in_([r.id for r in rows]))
            .values(status="running", updated_at=iso(now))
        )
    return [Job(id=r.id, kind=r.kind, ref_id=r.ref_id, attempts=r.attempts, polls=r.polls) for r in rows]


async def reset_running(conn: AsyncConnection, now: datetime) -> int:
    """起動時に、前回の停止で running のまま残ったジョブを戻す。"""
    res = await conn.execute(
        sa.update(jobs).where(jobs.c.status == "running").values(status="pending", updated_at=iso(now))
    )
    return res.rowcount


async def done(conn: AsyncConnection, job: Job, now: datetime) -> None:
    await conn.execute(
        sa.update(jobs).where(jobs.c.id == job.id).values(status="done", last_error=None, updated_at=iso(now))
    )


async def poll_later(conn: AsyncConnection, job: Job, now: datetime, delay: timedelta) -> None:
    """失敗ではない待ち (動画の変換待ちなど)。attempts は増やさない。"""
    await conn.execute(
        sa.update(jobs)
        .where(jobs.c.id == job.id)
        .values(status="pending", polls=job.polls + 1, next_run_at=iso(now + delay), updated_at=iso(now))
    )


async def give_up(conn: AsyncConnection, job: Job, now: datetime, error: str) -> None:
    """再試行しても直らない失敗。すぐ failed にする。"""
    await conn.execute(
        sa.update(jobs)
        .where(jobs.c.id == job.id)
        .values(status="failed", attempts=job.attempts + 1, last_error=error[:500], updated_at=iso(now))
    )


async def failed_attempt(conn: AsyncConnection, job: Job, now: datetime, error: str) -> bool:
    """失敗を 1 回数える。回数を使い切ったら failed にして True を返す。"""
    attempts = job.attempts + 1
    final = attempts >= MAX_ATTEMPTS
    await conn.execute(
        sa.update(jobs)
        .where(jobs.c.id == job.id)
        .values(
            status="failed" if final else "pending",
            attempts=attempts,
            last_error=error[:500],
            next_run_at=iso(now + backoff(attempts)),
            updated_at=iso(now),
        )
    )
    return final
