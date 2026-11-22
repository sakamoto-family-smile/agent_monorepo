"""定期処理 (backend のプロセスの中で 1 分おきに見る)。

- 毎日 BACKUP_HOUR (既定 3 時) 以降に、その日のバックアップがまだなければ作る。
  Mac mini が止まっていて過ぎた分は、起動後すぐに作る
- HEALTHCHECK_PING_URL があれば 5 分おきに ping する (止まったら Healthchecks.io から知らせが来る)。
  バックアップに失敗したら /fail に ping し、push でも知らせる
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx

from app import backup
from app.deps import Deps
from app.push import push_text

logger = logging.getLogger(__name__)

TICK_SECONDS = 60
PING_INTERVAL = timedelta(minutes=5)
PING_TIMEOUT = 10.0


@dataclass
class Scheduler:
    deps: Deps
    http: httpx.AsyncClient | None = None
    last_ping: datetime | None = None
    # 失敗の push は 1 日 1 回 (毎分やり直すので、そのたびには送らない)
    notified_days: set[str] = field(default_factory=set)

    async def tick(self) -> None:
        now = self.deps.clock()
        ok = await self._backup_if_due(now)
        if self.deps.settings.healthcheck_ping_url and (
            not ok or self.last_ping is None or now - self.last_ping >= PING_INTERVAL
        ):
            await self._ping(ok)
            self.last_ping = now

    async def _backup_if_due(self, now: datetime) -> bool:
        settings = self.deps.settings
        local = now.astimezone(settings.tz)
        if local.hour < settings.backup_hour or backup.backup_path(settings.paths, local.date()).exists():
            return True
        try:
            await asyncio.to_thread(backup.run_backup, settings.paths, local.date(), settings.backup_keep)
            return True
        except Exception as e:  # どの失敗も知らせて、次の tick でやり直す
            logger.exception("backup failed")
            day = local.date().isoformat()
            if day not in self.notified_days:
                self.notified_days.add(day)
                await self._notify_failure(day, f"{type(e).__name__}: {e}")
            return False

    async def _notify_failure(self, day: str, error: str) -> None:
        for user_id in sorted(self.deps.settings.allowed_user_ids):
            try:
                await push_text(
                    self.deps,
                    to=user_id,
                    kind="failure",
                    key=f"backup-failed-{day}",
                    body=f"⚠️ golf.db のバックアップに失敗しました（{day}）。\n理由: {error[:100]}",
                )
            except Exception:  # 通知の失敗でバックアップのやり直しを止めない
                logger.exception("failed to push backup failure")

    async def _ping(self, ok: bool) -> None:
        url = self.deps.settings.healthcheck_ping_url.rstrip("/")
        client = self.http or httpx.AsyncClient(timeout=PING_TIMEOUT)
        try:
            await client.get(url if ok else f"{url}/fail")
        except httpx.HTTPError as e:
            logger.warning("healthcheck ping failed: %s", type(e).__name__)
        finally:
            if self.http is None:
                await client.aclose()

    async def run_forever(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.tick()
            except Exception:  # ループを止めない
                logger.exception("scheduler tick failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=TICK_SECONDS)
            except TimeoutError:
                pass
