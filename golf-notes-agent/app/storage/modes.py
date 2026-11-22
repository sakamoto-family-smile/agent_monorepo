"""入力モード (§4.3.1)。リッチメニューで送る種類を先に選び、その後に届いたものをその種類として扱う。

- モードは最後の操作から 30 分で切れ、メモモード (既定。行なし) に戻る
- モード中に何か送るたびに期限を延ばす
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.storage.tables import input_modes
from app.timeutil import iso

TTL = timedelta(minutes=30)
MEMO = "memo"
# course はラウンド開始の直後にコース名を受け取るための内部のモード (ボタンはない)
MODES = ("metrics", "video", "score", "course")
LABELS = {"metrics": "計測モード", "video": "動画モード", "score": "スコアモード", "course": "コース名の入力"}


@dataclass(frozen=True)
class Mode:
    name: str = MEMO
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str | None:
        return LABELS.get(self.name)


async def current(conn: AsyncConnection, user_id: str, now: datetime) -> Mode:
    row = (await conn.execute(sa.select(input_modes).where(input_modes.c.user_id == user_id))).first()
    if row is None:
        return Mode()
    if row.expires_at <= iso(now):
        await clear(conn, user_id)
        return Mode()
    return Mode(name=row.mode, params=json.loads(row.params_json))


async def set_mode(
    conn: AsyncConnection, user_id: str, name: str, now: datetime, params: dict[str, Any] | None = None
) -> Mode:
    if name == MEMO:
        await clear(conn, user_id)
        return Mode()
    if name not in MODES:
        raise ValueError(f"unknown mode: {name}")
    values = {
        "mode": name,
        "params_json": json.dumps(params or {}, ensure_ascii=False, sort_keys=True),
        "expires_at": iso(now + TTL),
        "updated_at": iso(now),
    }
    await conn.execute(
        insert(input_modes)
        .values(user_id=user_id, **values)
        .on_conflict_do_update(index_elements=["user_id"], set_=values)
    )
    return Mode(name=name, params=params or {})


async def extend(conn: AsyncConnection, user_id: str, now: datetime) -> None:
    await conn.execute(
        sa.update(input_modes)
        .where(input_modes.c.user_id == user_id)
        .values(expires_at=iso(now + TTL), updated_at=iso(now))
    )


async def clear(conn: AsyncConnection, user_id: str) -> None:
    await conn.execute(sa.delete(input_modes).where(input_modes.c.user_id == user_id))
