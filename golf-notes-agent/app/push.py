"""push の送信と通数の管理 (§4.3.2)。

reply は webhook の中で結果が決まるものだけに使い、あとで動くジョブの結果は push で返す。
push は LINE の無料の通数 (月 200 通) を超えないよう push_log で数え、上限を超えたら
失敗の通知と週次レポート以外を止める。
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

import sqlalchemy as sa

from app.deps import Deps
from app.line.api import text
from app.storage.tables import push_log
from app.timeutil import iso, month_start

logger = logging.getLogger(__name__)

# 上限を超えても送るもの (保存の失敗は必ず知らせる)
ESSENTIAL = frozenset({"failure", "weekly"})
RETRY_NAMESPACE = uuid.UUID("5d0f3f6e-6c43-4a55-9f5e-1f3d2b7a9c10")


async def sent_this_month(deps: Deps, now: datetime) -> int:
    since = iso(month_start(now, deps.settings.tz))
    async with deps.engine.connect() as conn:
        return int(
            (await conn.execute(sa.select(sa.func.count()).where(push_log.c.sent_at >= since))).scalar_one()
        )


async def push_text(deps: Deps, *, to: str, kind: str, key: str, body: str) -> bool:
    """送ったら True。上限で止めたら False。

    key は同じ通知を二重に送らないための識別子 (X-Line-Retry-Key のもと)。
    """
    now = deps.clock()
    if kind not in ESSENTIAL and await sent_this_month(deps, now) >= deps.settings.push_monthly_limit:
        logger.warning("push skipped (monthly limit): kind=%s", kind)
        return False
    retry_key = str(uuid.uuid5(RETRY_NAMESPACE, key))
    await deps.line.push(to, [text(body)], retry_key=retry_key)
    async with deps.engine.begin() as conn:
        await conn.execute(sa.insert(push_log).values(kind=kind, sent_at=iso(now)))
    return True
