"""同時分析数の上限 (services.analysis_limiter, PROPOSAL-0013) のテスト。"""

from __future__ import annotations

import asyncio

from services.analysis_limiter import AnalysisSlots


async def test_limits_concurrency_and_notifies_waiters_once():
    slots = AnalysisSlots(max_concurrency=2)
    running = 0
    peak = 0
    notices: list[int] = []
    release = asyncio.Event()

    async def job(i: int) -> None:
        nonlocal running, peak

        async def on_wait() -> None:
            notices.append(i)

        async with slots.slot(on_wait=on_wait):
            running += 1
            peak = max(peak, running)
            await release.wait()
            running -= 1

    tasks = [asyncio.create_task(job(i)) for i in range(4)]
    await asyncio.sleep(0.01)
    assert running == 2
    assert slots.waiting == 2
    release.set()
    await asyncio.gather(*tasks)

    assert peak == 2
    assert sorted(notices) == [2, 3]
    assert slots.waiting == 0


async def test_zero_means_unlimited():
    slots = AnalysisSlots(max_concurrency=0)
    running = 0
    release = asyncio.Event()

    async def job() -> None:
        nonlocal running
        async with slots.slot():
            running += 1
            await release.wait()

    tasks = [asyncio.create_task(job()) for _ in range(5)]
    await asyncio.sleep(0.01)
    assert running == 5
    release.set()
    await asyncio.gather(*tasks)


async def test_on_wait_failure_does_not_block_the_job():
    slots = AnalysisSlots(max_concurrency=1)
    done: list[str] = []
    release = asyncio.Event()

    async def first() -> None:
        async with slots.slot():
            await release.wait()
            done.append("first")

    async def broken_notice() -> None:
        raise RuntimeError("LINE down")

    async def second() -> None:
        async with slots.slot(on_wait=broken_notice):
            done.append("second")

    t1 = asyncio.create_task(first())
    await asyncio.sleep(0)
    t2 = asyncio.create_task(second())
    await asyncio.sleep(0.01)
    release.set()
    await asyncio.gather(t1, t2)

    assert done == ["first", "second"]


async def test_slot_is_released_when_job_raises():
    slots = AnalysisSlots(max_concurrency=1)

    async def failing() -> None:
        async with slots.slot():
            raise ValueError("boom")

    try:
        await failing()
    except ValueError:
        pass

    async with slots.slot():
        pass  # 解放されていなければここで固まる


def test_counts_consecutive_failures():
    slots = AnalysisSlots(max_concurrency=1)

    slots.record_result(ok=False)
    slots.record_result(ok=False)
    assert slots.consecutive_failures == 2

    slots.record_result(ok=True)
    assert slots.consecutive_failures == 0
