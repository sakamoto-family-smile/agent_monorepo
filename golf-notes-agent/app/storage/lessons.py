"""レッスン計測の保存 (lesson_captures と launch_metrics)。

検算に引っかからなければ確定 (confirmed)、引っかかった球があれば確認待ち (pending) にして、
人が「確定」か「取消」(rejected) を選ぶ。分析で使うのは確定したものだけ (v_launch_metrics)。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.lesson.checks import Flag
from app.lesson.parser import COLUMNS, PARSER_VERSION, Shot
from app.storage.tables import launch_metrics, lesson_captures
from app.timeutil import iso

STATUSES = ("confirmed", "rejected")


@dataclass(frozen=True)
class Capture:
    id: int
    session_id: int
    status: str


async def save_text_capture(
    conn: AsyncConnection,
    *,
    session_id: int,
    raw_event_id: int,
    raw_text: str,
    shots: list[Shot],
    flags: list[list[Flag]],
    now: datetime,
) -> Capture:
    status = "pending" if any(flags) else "confirmed"
    res = await conn.execute(
        sa.insert(lesson_captures).values(
            session_id=session_id,
            source="text",
            raw_event_id=raw_event_id,
            parser_version=PARSER_VERSION,
            raw_text=raw_text,
            status=status,
            created_at=iso(now),
        )
    )
    capture_id = int(res.inserted_primary_key[0])
    for shot, shot_flags in zip(shots, flags, strict=True):
        await conn.execute(
            sa.insert(launch_metrics).values(
                capture_id=capture_id,
                shot_no=shot.shot_no,
                shot_at=iso(shot.shot_at),
                club=shot.club,
                **{c: shot.values.get(c) for c in COLUMNS},
                labels_json=json.dumps({"club": shot.club_label, **shot.labels}, ensure_ascii=False),
                extra_json=json.dumps(shot.extra, ensure_ascii=False),
                check_flags=json.dumps([f.code for f in shot_flags]),
            )
        )
    return Capture(id=capture_id, session_id=session_id, status=status)


async def get(conn: AsyncConnection, capture_id: int) -> Capture | None:
    row = (
        await conn.execute(
            sa.select(lesson_captures).where(
                lesson_captures.c.id == capture_id, lesson_captures.c.deleted_at.is_(None)
            )
        )
    ).first()
    return Capture(id=row.id, session_id=row.session_id, status=row.status) if row else None


async def set_status(conn: AsyncConnection, capture_id: int, status: str) -> bool:
    if status not in STATUSES:
        raise ValueError(status)
    res = await conn.execute(
        sa.update(lesson_captures)
        .where(lesson_captures.c.id == capture_id, lesson_captures.c.deleted_at.is_(None))
        .values(status=status)
    )
    return res.rowcount == 1


async def move(conn: AsyncConnection, capture_id: int, session_id: int) -> bool:
    res = await conn.execute(
        sa.update(lesson_captures)
        .where(lesson_captures.c.id == capture_id, lesson_captures.c.deleted_at.is_(None))
        .values(session_id=session_id)
    )
    return res.rowcount == 1
