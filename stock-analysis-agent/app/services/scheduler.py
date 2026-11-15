"""backend 内の定期処理 (PROPOSAL-0013 §3.3)。

ローカル常駐では SQLite に書くプロセスを backend の 1 つに限るため、日次ジョブを launchd ではなく
ここで動かす (security-platform の各サービスが `serve` で内部スケジュールを持つのと同じ形)。
GCP では Cloud Run Job + Scheduler を使うので、どのジョブも既定は無効。

ジョブ:
- edinet_index  毎日 EDINET_SCHEDULE_TIME (JST)。EDINET の書類一覧を rolling 窓で upsert
- backup        毎日 BACKUP_TIME (JST)。SQLite を data/backups に世代保存
- health        HEALTH_CHECK_INTERVAL_SECONDS ごと。監視項目を見て、変化があれば管理者に LINE

日次ジョブは再起動をまたいで最終成功時刻を SCHEDULER_STATE_PATH に残し、止まっている間に
過ぎた回は起動後すぐ 1 回実行する。失敗したら RETRY_DELAY 後にやり直す。
成否は Healthchecks.io に `stock-<job>` で ping する (health は `stock-backend` の生存 ping も送る)。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

import config
from services.healthcheck_ping import Pinger, make_pinger

logger = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")
RETRY_DELAY = timedelta(hours=1)
STARTUP_DELAY = timedelta(seconds=30)  # 起動直後の DB 初期化・migration と重ならないよう少し待つ


@dataclass(frozen=True)
class Job:
    name: str
    run: Callable[[], Awaitable[None]]
    daily_at: time | None = None  # JST
    interval: timedelta | None = None
    writes_db: bool = False


def parse_hhmm(value: str) -> time:
    hh, _, mm = value.partition(":")
    return time(int(hh), int(mm))


class SchedulerState:
    """日次ジョブの最終成功時刻 (UTC ISO) を JSON ファイルに残す。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, str] = {}
        if path.exists():
            try:
                self._data = dict(json.loads(path.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                logger.warning("scheduler state is unreadable; starting fresh (%s)", path)

    def last_success(self, job: str) -> datetime | None:
        raw = self._data.get(job)
        return datetime.fromisoformat(raw) if raw else None

    def record_success(self, job: str, at: datetime) -> None:
        self._data = {**self._data, job: at.isoformat()}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        tmp.replace(self._path)


def next_daily_run(
    now: datetime,
    at: time,
    last_success: datetime | None,
    last_failure: datetime | None = None,
) -> datetime:
    """次に実行する時刻 (UTC)。直近の予定時刻より後に成功していなければ、すぐ (または再試行時刻に)。"""
    local_now = now.astimezone(JST)
    upcoming = datetime.combine(local_now.date(), at, tzinfo=JST)
    if upcoming <= local_now:
        upcoming += timedelta(days=1)
    previous = upcoming - timedelta(days=1)
    if last_success is None or last_success < previous:
        if last_failure is not None and last_failure >= previous:
            return min(last_failure + RETRY_DELAY, upcoming.astimezone(UTC))
        return now
    return upcoming.astimezone(UTC)


class Scheduler:
    def __init__(
        self,
        jobs: list[Job],
        *,
        state: SchedulerState,
        ping: Pinger | None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._jobs = jobs
        self._state = state
        self._ping = ping
        self._clock = clock
        self._db_lock = asyncio.Lock()
        self._last_failure: dict[str, datetime] = {}
        self._tasks: list[asyncio.Task] = []

    @property
    def state(self) -> SchedulerState:
        return self._state

    async def run_job(self, job: Job) -> bool:
        started = self._clock()
        try:
            if job.writes_db:
                async with self._db_lock:
                    await job.run()
            else:
                await job.run()
            ok = True
        except Exception:
            logger.exception("scheduled job failed: %s", job.name)
            ok = False
        if ok:
            self._last_failure.pop(job.name, None)
            if job.daily_at is not None:
                self._state.record_success(job.name, started)
        else:
            self._last_failure[job.name] = started
        if self._ping is not None:
            await self._ping(job.name, ok)
        return ok

    def next_run(self, job: Job, now: datetime) -> datetime:
        if job.daily_at is not None:
            return next_daily_run(
                now, job.daily_at, self._state.last_success(job.name), self._last_failure.get(job.name)
            )
        assert job.interval is not None
        return now + job.interval

    async def _loop(self, job: Job) -> None:
        # 一定間隔のジョブ (health) は 1 周期待ってから始める。起動直後の取りこぼし分の日次ジョブ
        # (backup など) が先に終わるので、「成功の記録なし」と誤って知らせない
        await asyncio.sleep(STARTUP_DELAY.total_seconds())
        while True:
            now = self._clock()
            due = self.next_run(job, now)
            await asyncio.sleep(max(0.0, (due - now).total_seconds()))
            await self.run_job(job)

    def start(self) -> None:
        for job in self._jobs:
            logger.info("scheduled job enabled: %s", job.name)
            self._tasks.append(asyncio.create_task(self._loop(job), name=f"scheduler-{job.name}"))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []


# ---------------------------------------------------------------------------
# ジョブの中身
# ---------------------------------------------------------------------------


async def _edinet_index_job() -> None:
    from batch.edinet_index_etl import _resolve_target_dates, run

    dates = _resolve_target_dates(
        rolling_days=config.settings.edinet_daily_window_days, from_date=None, to_date=None
    )
    summary = await run(dates)
    logger.info("EDINET index job: %s", summary)
    if summary["failed_days"]:
        raise RuntimeError(f"EDINET index: {summary['failed_days']} 日分の取得に失敗しました")


async def _backup_job() -> None:
    from services.backup import run_backup

    await run_backup()


def _make_health_job(scheduler_ref: list[Scheduler], ping: Pinger | None) -> Callable[[], Awaitable[None]]:
    from services.analysis_limiter import get_analysis_slots
    from services.health_monitor import HealthMonitor, collect_checks
    from services.line_client import get_line_bot_client

    async def notify(text: str) -> None:
        client = get_line_bot_client()
        if client is None:
            logger.warning("LINE is not configured; health notice was not sent")
            return
        for user_id in config.settings.health_notify_user_id_list:
            await client.push_text(to=user_id, text=text)

    monitor = HealthMonitor(notify)

    async def health_job() -> None:
        if ping is not None:
            await ping("backend", True)  # 生存 ping: 途絶えたら Mac / Docker / backend の停止
        async with httpx.AsyncClient() as client:
            checks = await collect_checks(
                now=datetime.now(UTC),
                last_success=scheduler_ref[0].state.last_success,
                consecutive_failures=get_analysis_slots().consecutive_failures,
                client=client,
            )
        await monitor.observe(checks)
        failed = [c for c in checks if not c.ok]
        if failed:
            raise RuntimeError("監視項目に異常があります: " + ", ".join(c.key for c in failed))

    return health_job


def build_scheduler() -> Scheduler | None:
    """設定で有効なジョブだけを持つ Scheduler を作る。1 つも無ければ None。"""
    s = config.settings
    ping = make_pinger(s.healthcheck_ping_base)
    ref: list[Scheduler] = []
    jobs: list[Job] = []
    if s.edinet_schedule_enabled:
        jobs.append(Job("edinet_index", _edinet_index_job, daily_at=parse_hhmm(s.edinet_schedule_time), writes_db=True))
    if s.backup_enabled:
        jobs.append(Job("backup", _backup_job, daily_at=parse_hhmm(s.backup_time), writes_db=True))
    if s.health_check_enabled:
        jobs.append(
            Job("health", _make_health_job(ref, ping), interval=timedelta(seconds=s.health_check_interval_seconds))
        )
    if not jobs:
        return None
    scheduler = Scheduler(jobs, state=SchedulerState(Path(s.scheduler_state_path)), ping=ping)
    ref.append(scheduler)
    return scheduler


_scheduler: Scheduler | None = None


async def start_scheduler() -> None:
    global _scheduler
    _scheduler = build_scheduler()
    if _scheduler is None:
        logger.info("scheduler disabled (no scheduled jobs enabled)")
        return
    _scheduler.start()


async def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        await _scheduler.stop()
        _scheduler = None


__all__ = [
    "Job",
    "Scheduler",
    "SchedulerState",
    "build_scheduler",
    "next_daily_run",
    "parse_hhmm",
    "start_scheduler",
    "stop_scheduler",
]
