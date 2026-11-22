"""backend 内の定期処理 (services.scheduler, PROPOSAL-0013) のテスト。"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pytest
from services import scheduler as sched
from services.scheduler import (
    Job,
    Scheduler,
    SchedulerState,
    next_daily_run,
    parse_hhmm,
)

import config

JST = sched.JST


def _jst(y, m, d, hh, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=JST).astimezone(UTC)


AT = time(2, 0)


def test_next_run_is_tonight_when_already_done_today():
    now = _jst(2026, 11, 15, 10)
    last = _jst(2026, 11, 15, 2, 1)

    assert next_daily_run(now, AT, last) == _jst(2026, 11, 16, 2)


def test_next_run_is_today_when_before_the_time():
    now = _jst(2026, 11, 15, 1, 30)
    last = _jst(2026, 11, 14, 2, 1)

    assert next_daily_run(now, AT, last) == _jst(2026, 11, 15, 2)


def test_missed_run_executes_immediately():
    now = _jst(2026, 11, 15, 10)
    last = _jst(2026, 11, 13, 2, 1)  # 11/14 と 11/15 の回を逃している

    assert next_daily_run(now, AT, last) == now


def test_first_start_without_state_executes_immediately():
    now = _jst(2026, 11, 15, 10)

    assert next_daily_run(now, AT, None) == now


def test_failed_run_retries_after_delay():
    now = _jst(2026, 11, 15, 2, 10)
    failed_at = _jst(2026, 11, 15, 2, 0)

    assert next_daily_run(now, AT, _jst(2026, 11, 14, 2), failed_at) == failed_at + sched.RETRY_DELAY


def test_retry_never_goes_past_the_next_scheduled_time():
    now = _jst(2026, 11, 16, 1, 50)
    failed_at = _jst(2026, 11, 16, 1, 30)

    assert next_daily_run(now, AT, _jst(2026, 11, 14, 2), failed_at) == _jst(2026, 11, 16, 2)


def test_parse_hhmm():
    assert parse_hhmm("02:30") == time(2, 30)


def test_state_survives_restart(tmp_path):
    path = tmp_path / "state.json"
    at = datetime(2026, 11, 15, 1, 2, 3, tzinfo=UTC)

    SchedulerState(path).record_success("backup", at)

    assert SchedulerState(path).last_success("backup") == at
    assert SchedulerState(path).last_success("edinet_index") is None


def test_unreadable_state_starts_fresh(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{broken", encoding="utf-8")

    assert SchedulerState(path).last_success("backup") is None


class _Pings:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    async def __call__(self, job: str, ok: bool) -> None:
        self.calls.append((job, ok))


async def test_run_job_records_success_and_pings(tmp_path):
    pings = _Pings()
    now = datetime(2026, 11, 15, 1, tzinfo=UTC)
    calls = []

    async def work() -> None:
        calls.append("ran")

    job = Job("backup", work, daily_at=AT, writes_db=True)
    s = Scheduler([job], state=SchedulerState(tmp_path / "s.json"), ping=pings, clock=lambda: now)

    assert await s.run_job(job) is True
    assert calls == ["ran"]
    assert pings.calls == [("backup", True)]
    assert s.state.last_success("backup") == now


async def test_run_job_failure_pings_fail_and_schedules_retry(tmp_path):
    pings = _Pings()
    now = _jst(2026, 11, 15, 2)

    async def broken() -> None:
        raise RuntimeError("EDINET down")

    job = Job("edinet_index", broken, daily_at=AT, writes_db=True)
    s = Scheduler([job], state=SchedulerState(tmp_path / "s.json"), ping=pings, clock=lambda: now)

    assert await s.run_job(job) is False
    assert pings.calls == [("edinet_index", False)]
    assert s.state.last_success("edinet_index") is None
    assert s.next_run(job, now) == now + sched.RETRY_DELAY


async def test_interval_job_does_not_touch_state(tmp_path):
    now = datetime(2026, 11, 15, tzinfo=UTC)

    async def work() -> None:
        return None

    job = Job("health", work, interval=timedelta(minutes=5))
    s = Scheduler([job], state=SchedulerState(tmp_path / "s.json"), ping=None, clock=lambda: now)

    await s.run_job(job)

    assert s.state.last_success("health") is None
    assert s.next_run(job, now) == now + timedelta(minutes=5)


def _set(monkeypatch, **values) -> None:
    defaults = {
        "edinet_schedule_enabled": False,
        "backup_enabled": False,
        "health_check_enabled": False,
        "healthcheck_ping_base": "",
    }
    for key, value in {**defaults, **values}.items():
        monkeypatch.setattr(config.settings, key, value)


def test_build_scheduler_returns_none_when_all_disabled(monkeypatch):
    _set(monkeypatch)

    assert sched.build_scheduler() is None


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ({"edinet_schedule_enabled": True}, ["edinet_index"]),
        ({"backup_enabled": True, "health_check_enabled": True}, ["backup", "health"]),
        (
            {"edinet_schedule_enabled": True, "backup_enabled": True, "health_check_enabled": True},
            ["edinet_index", "backup", "health"],
        ),
    ],
)
def test_build_scheduler_includes_only_enabled_jobs(monkeypatch, tmp_path, flags, expected):
    _set(monkeypatch, **flags)
    monkeypatch.setattr(config.settings, "scheduler_state_path", str(tmp_path / "s.json"))

    s = sched.build_scheduler()

    assert s is not None
    assert [j.name for j in s._jobs] == expected


async def test_edinet_job_raises_when_some_days_failed(monkeypatch):
    import batch.edinet_index_etl as etl

    async def fake_run(dates):
        return {"target_days": len(dates), "succeeded_days": len(dates) - 1, "failed_days": 1, "upserted_documents": 3}

    monkeypatch.setattr(etl, "run", fake_run)

    with pytest.raises(RuntimeError, match="1 日分"):
        await sched._edinet_index_job()


async def test_interval_job_waits_one_period_before_first_run(tmp_path, monkeypatch):
    """起動直後に health を走らせると、まだ backup が無く誤って異常を知らせてしまう。"""
    import asyncio

    sleeps: list[float] = []
    ran: list[str] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) >= 3:
            raise asyncio.CancelledError

    async def work() -> None:
        ran.append("health")

    monkeypatch.setattr(sched.asyncio, "sleep", fake_sleep)
    now = datetime(2026, 11, 15, tzinfo=UTC)
    job = Job("health", work, interval=timedelta(minutes=5))
    s = Scheduler([job], state=SchedulerState(tmp_path / "s.json"), ping=None, clock=lambda: now)

    try:
        await s._loop(job)
    except asyncio.CancelledError:
        pass

    assert sleeps[:2] == [sched.STARTUP_DELAY.total_seconds(), 300.0]
    assert ran == ["health"]
