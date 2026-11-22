"""セッション (練習 / レッスン / ラウンド 1 回) の検索・作成・自動終了。

- 開いているセッション: 開始ボタンで作り、終了ボタンか最終操作から 6 時間で終わる。
  日付が変わっただけでは終わらない (0 時をまたぐ練習も 1 つ)
- 仮のセッション: ボタンを押さずに送ったものの入れ先。日付と種類ごとに 1 つ作り、
  開いているセッションとしては扱わない
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.storage.tables import sessions
from app.timeutil import iso

IDLE_END = timedelta(hours=6)
KINDS = ("practice", "lesson", "round")
KIND_LABELS = {"practice": "練習", "lesson": "レッスン", "round": "ラウンド"}


@dataclass(frozen=True)
class SessionRef:
    id: int
    kind: str
    date: str
    provisional: bool

    @property
    def label(self) -> str:
        _, month, day = self.date.split("-")
        suffix = "（仮）" if self.provisional else ""
        return f"{int(month)}/{int(day)} の{KIND_LABELS[self.kind]}{suffix}"


def _ref(row: sa.Row) -> SessionRef:
    return SessionRef(id=row.id, kind=row.kind, date=row.date, provisional=bool(row.provisional))


async def end_idle(conn: AsyncConnection, now: datetime) -> int:
    """最終操作から 6 時間たった開いているセッションを終了する。終了した件数を返す。"""
    cutoff = iso(now - IDLE_END)
    res = await conn.execute(
        sa.update(sessions)
        .where(
            sessions.c.ended_at.is_(None),
            sessions.c.provisional.is_(False),
            sessions.c.last_activity_at <= cutoff,
        )
        .values(ended_at=sessions.c.last_activity_at, end_reason="idle")
    )
    return res.rowcount


async def open_session(conn: AsyncConnection, now: datetime) -> SessionRef | None:
    await end_idle(conn, now)
    row = (
        await conn.execute(
            sa.select(sessions)
            .where(sessions.c.ended_at.is_(None), sessions.c.provisional.is_(False))
            .order_by(sessions.c.started_at.desc())
            .limit(1)
        )
    ).first()
    return _ref(row) if row else None


async def provisional_session(
    conn: AsyncConnection, day: date, kind: str, now: datetime
) -> SessionRef:
    row = (
        await conn.execute(
            sa.select(sessions).where(
                sessions.c.date == day.isoformat(),
                sessions.c.kind == kind,
                sessions.c.provisional.is_(True),
            )
        )
    ).first()
    if row:
        return _ref(row)
    res = await conn.execute(
        sa.insert(sessions).values(
            kind=kind,
            date=day.isoformat(),
            provisional=True,
            started_at=iso(now),
            last_activity_at=iso(now),
        )
    )
    return SessionRef(id=int(res.inserted_primary_key[0]), kind=kind, date=day.isoformat(), provisional=True)


async def session_for_item(conn: AsyncConnection, now: datetime, tz: ZoneInfo) -> SessionRef:
    """メモ・動画・画像・スコアの入れ先 (届いた時刻が基準)。開いているセッション、無ければ当日の仮の練習。"""
    current = await open_session(conn, now)
    if current:
        await touch(conn, current.id, now)
        return current
    return await provisional_session(conn, now.astimezone(tz).date(), "practice", now)


async def touch(conn: AsyncConnection, session_id: int, now: datetime) -> None:
    await conn.execute(
        sa.update(sessions).where(sessions.c.id == session_id).values(last_activity_at=iso(now))
    )


async def get(conn: AsyncConnection, session_id: int) -> SessionRef | None:
    row = (await conn.execute(sa.select(sessions).where(sessions.c.id == session_id))).first()
    return _ref(row) if row else None


async def start(conn: AsyncConnection, kind: str, now: datetime, tz: ZoneInfo) -> SessionRef:
    """開始ボタン。開いているセッションがあれば終了してから新しく作る。"""
    if kind not in KINDS:
        raise ValueError(f"unknown session kind: {kind}")
    current = await open_session(conn, now)
    if current:
        await end(conn, current.id, now)
    day = now.astimezone(tz).date().isoformat()
    res = await conn.execute(
        sa.insert(sessions).values(
            kind=kind, date=day, provisional=False, started_at=iso(now), last_activity_at=iso(now)
        )
    )
    return SessionRef(id=int(res.inserted_primary_key[0]), kind=kind, date=day, provisional=False)


async def end(conn: AsyncConnection, session_id: int, now: datetime) -> None:
    await conn.execute(
        sa.update(sessions)
        .where(sessions.c.id == session_id, sessions.c.ended_at.is_(None))
        .values(ended_at=iso(now), end_reason="manual")
    )


async def set_course(conn: AsyncConnection, session_id: int, course_id: int) -> None:
    await conn.execute(sa.update(sessions).where(sessions.c.id == session_id).values(course_id=course_id))
