"""コンテナ常駐用の簡易スケジューラ。

ジョブは逐次実行する (1 つの SQLite ファイルへの書き込みプロセスを 1 つに保つため)。
最終成功時刻は呼び出し側が DB などから返すので、再起動しても間隔を守れる。
失敗が続くジョブは retry_after から倍々に待つ (上限は max_backoff と実行間隔の小さい方)。
3GB の全量取得が失敗し続けても、数分おきに取り直してディスクと回線を埋めないため。
"""
from __future__ import annotations

import logging
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from .timeutil import utc_now

logger = logging.getLogger(__name__)

MAX_SLEEP_SECONDS = 60.0


@dataclass(frozen=True)
class Job:
    name: str
    interval: timedelta
    run: Callable[[], None]


def due_jobs(
    jobs: list[Job], last_success: Callable[[str], datetime | None], now: datetime
) -> list[Job]:
    due = []
    for job in jobs:
        last = last_success(job.name)
        if last is None or now - last >= job.interval:
            due.append(job)
    return due


def seconds_until_next(
    jobs: list[Job], last_success: Callable[[str], datetime | None], now: datetime
) -> float:
    waits = []
    for job in jobs:
        last = last_success(job.name)
        waits.append(0.0 if last is None else (last + job.interval - now).total_seconds())
    return max(0.0, min(waits, default=MAX_SLEEP_SECONDS))


class Scheduler:
    def __init__(
        self,
        jobs: list[Job],
        last_success: Callable[[str], datetime | None],
        *,
        retry_after: timedelta = timedelta(minutes=5),
        max_backoff: timedelta = timedelta(hours=6),
        on_result: Callable[[str, bool], None] | None = None,
    ) -> None:
        self._jobs = jobs
        self._last_success = last_success
        self._retry_after = retry_after
        self._max_backoff = max_backoff
        self._on_result = on_result
        self._failed_at: dict[str, datetime] = {}
        self._failures: dict[str, int] = {}
        self._stopping = False

    def stop(self, *_args: object) -> None:
        self._stopping = True

    def backoff(self, name: str) -> timedelta:
        job = next(j for j in self._jobs if j.name == name)
        n = self._failures.get(name, 0)
        wait = self._retry_after * (2 ** max(n - 1, 0))
        return min(wait, self._max_backoff, max(job.interval, self._retry_after))

    def _effective_last(self, name: str) -> datetime | None:
        """失敗したジョブはバックオフが明けるまで再実行しない。"""
        last = self._last_success(name)
        failed = self._failed_at.get(name)
        job = next(j for j in self._jobs if j.name == name)
        if failed and (last is None or failed > last):
            return failed - job.interval + self.backoff(name)
        return last

    def _notify(self, name: str, ok: bool) -> None:
        if self._on_result is None:
            return
        try:
            self._on_result(name, ok)
        except Exception:  # 通知の失敗でジョブを止めない
            logger.warning("job result notification failed: %s", name, exc_info=True)

    def run_once(self) -> list[str]:
        ran = []
        for job in due_jobs(self._jobs, self._effective_last, utc_now()):
            if self._stopping:
                break
            logger.info("job start: %s", job.name)
            try:
                job.run()
                self._failed_at.pop(job.name, None)
                self._failures.pop(job.name, None)
                logger.info("job done: %s", job.name)
                self._notify(job.name, True)
            except Exception:  # ジョブ単位で隔離し、他のジョブは止めない
                self._failed_at[job.name] = utc_now()
                self._failures[job.name] = self._failures.get(job.name, 0) + 1
                logger.exception(
                    "job failed: %s (%d in a row, next retry in %s)",
                    job.name, self._failures[job.name], self.backoff(job.name),
                )
                self._notify(job.name, False)
            ran.append(job.name)
        return ran

    def run_forever(self) -> None:
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        while not self._stopping:
            self.run_once()
            wait = seconds_until_next(self._jobs, self._effective_last, utc_now())
            deadline = time.monotonic() + min(max(wait, 1.0), MAX_SLEEP_SECONDS)
            while not self._stopping and time.monotonic() < deadline:
                time.sleep(1.0)
        logger.info("scheduler stopped")
