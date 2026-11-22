"""ジョブの実行。backend のプロセスの中で数秒おきに期限の来たジョブを動かす。"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta

from app.deps import Deps
from app.jobs import queue
from app.jobs.queue import Job

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 2.0


class PollLater(Exception):
    """失敗ではなく、時間をおいてもう一度見る (動画の変換待ちなど)。"""

    def __init__(self, delay: timedelta) -> None:
        super().__init__(f"poll later ({delay})")
        self.delay = delay


class PermanentError(Exception):
    """再試行しても直らない失敗 (LINE 側でコンテンツが消えた、など)。"""


Handler = Callable[[Deps, Job], Awaitable[None]]
FailureHook = Callable[[Deps, Job, str], Awaitable[None]]


@dataclass(frozen=True)
class JobKind:
    run: Handler
    on_failed: FailureHook | None = None


@dataclass
class Worker:
    deps: Deps
    kinds: dict[str, JobKind] = field(default_factory=dict)

    async def run_once(self) -> int:
        now = self.deps.clock()
        async with self.deps.engine.begin() as conn:
            due = await queue.claim_due(conn, now)
        for job in due:
            await self._run(job)
        return len(due)

    async def _run(self, job: Job) -> None:
        kind = self.kinds.get(job.kind)
        final = False
        error = ""
        try:
            if kind is None:
                raise PermanentError(f"unknown job kind: {job.kind}")
            await kind.run(self.deps, job)
        except PollLater as e:
            async with self.deps.engine.begin() as conn:
                await queue.poll_later(conn, job, self.deps.clock(), e.delay)
            return
        except PermanentError as e:
            error = str(e) or type(e).__name__
            final = True
            async with self.deps.engine.begin() as conn:
                await queue.give_up(conn, job, self.deps.clock(), error)
        except Exception as e:  # noqa: BLE001 — どの失敗も記録して再試行に回す
            error = f"{type(e).__name__}: {e}"
            logger.warning("job %s #%d failed: %s", job.kind, job.ref_id, error)
            async with self.deps.engine.begin() as conn:
                final = await queue.failed_attempt(conn, job, self.deps.clock(), error)
        else:
            async with self.deps.engine.begin() as conn:
                await queue.done(conn, job, self.deps.clock())
            return
        if final:
            logger.error("job %s #%d gave up: %s", job.kind, job.ref_id, error)
            if kind and kind.on_failed:
                try:
                    await kind.on_failed(self.deps, job, error)
                except Exception:  # 通知の失敗でワーカーを止めない
                    logger.exception("job failure hook failed")

    async def run_forever(self, stop: asyncio.Event) -> None:
        async with self.deps.engine.begin() as conn:
            reset = await queue.reset_running(conn, self.deps.clock())
        if reset:
            logger.info("reset %d running jobs", reset)
        while not stop.is_set():
            try:
                await self.run_once()
            except Exception:  # DB の一時的なエラーなどでループを止めない
                logger.exception("worker loop error")
            try:
                await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL_SECONDS)
            except TimeoutError:
                pass
