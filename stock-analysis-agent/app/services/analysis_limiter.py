"""in-process 実行時の同時分析数の上限 (PROPOSAL-0013 §4.8)。

GCP では Cloud Tasks の queue が同時実行数を抑えていたが、ローカル (TASKS_ENABLED=false) では
BackgroundTasks がそのまま走るため、ここで上限をかける。上限に達しているときは待たせ、
待ちが発生したことを 1 回だけ利用者に知らせる。

あわせて、直近の分析の連続失敗回数を数える (死活監視の `analysis` 項目が見る)。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import config

logger = logging.getLogger(__name__)


class AnalysisSlots:
    def __init__(self, max_concurrency: int) -> None:
        self._max = max_concurrency
        self._sem = asyncio.Semaphore(max_concurrency) if max_concurrency > 0 else None
        self._waiting = 0
        self._consecutive_failures = 0

    @property
    def waiting(self) -> int:
        return self._waiting

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    def record_result(self, *, ok: bool) -> None:
        self._consecutive_failures = 0 if ok else self._consecutive_failures + 1

    @asynccontextmanager
    async def slot(self, *, on_wait: Callable[[], Awaitable[None]] | None = None) -> AsyncIterator[None]:
        if self._sem is None:
            yield
            return
        if self._sem.locked():
            self._waiting += 1
            logger.info("analysis queued (max=%d, waiting=%d)", self._max, self._waiting)
            try:
                if on_wait is not None:
                    try:
                        await on_wait()
                    except Exception:
                        logger.exception("failed to send queued notice")
                await self._sem.acquire()
            finally:
                self._waiting -= 1
        else:
            await self._sem.acquire()
        try:
            yield
        finally:
            self._sem.release()


_slots: AnalysisSlots | None = None


def get_analysis_slots() -> AnalysisSlots:
    global _slots
    if _slots is None:
        _slots = AnalysisSlots(config.settings.analysis_max_concurrency)
    return _slots


def reset_analysis_slots() -> None:
    """テスト用。"""
    global _slots
    _slots = None


__all__ = ["AnalysisSlots", "get_analysis_slots", "reset_analysis_slots"]
