"""保存したもの (メモ・動画・画像) の作成と取消。

取消は論理削除 (deleted_at を入れる)。原本 (raw_events・data/raw/・data/media/) は消さない。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.storage.tables import lesson_captures, media, memos, raw_events, score_texts
from app.timeutil import iso

# 取消の対象になるテーブルと、返信での呼び方
UNDOABLE: dict[str, tuple[sa.Table, str]] = {
    "memo": (memos, "メモ"),
    "media": (media, "動画・画像"),
    "score": (score_texts, "スコア"),
    "capture": (lesson_captures, "計測"),
}


# 動画・画像ごとに付けられる情報
TAGS = {"video": ("angle", "club"), "image": ("purpose",)}


@dataclass(frozen=True)
class Entry:
    kind: str
    id: int
    label: str
    created_at: str


async def add_memo(
    conn: AsyncConnection, *, session_id: int, raw_event_id: int, text: str, now: datetime
) -> int:
    res = await conn.execute(
        sa.insert(memos).values(
            session_id=session_id, raw_event_id=raw_event_id, text=text, created_at=iso(now)
        )
    )
    return int(res.inserted_primary_key[0])


async def memo_exists(conn: AsyncConnection, raw_event_id: int) -> bool:
    row = (
        await conn.execute(
            sa.select(memos.c.id).where(memos.c.raw_event_id == raw_event_id, memos.c.deleted_at.is_(None))
        )
    ).first()
    return row is not None


async def add_media(
    conn: AsyncConnection,
    *,
    session_id: int,
    raw_event_id: int,
    kind: str,
    now: datetime,
    duration_ms: int | None = None,
) -> int:
    res = await conn.execute(
        sa.insert(media).values(
            session_id=session_id,
            raw_event_id=raw_event_id,
            kind=kind,
            status="pending",
            duration_ms=duration_ms,
            source="line",
            created_at=iso(now),
        )
    )
    return int(res.inserted_primary_key[0])


async def add_score(
    conn: AsyncConnection, *, session_id: int, raw_event_id: int, text: str, now: datetime
) -> int:
    res = await conn.execute(
        sa.insert(score_texts).values(
            session_id=session_id, raw_event_id=raw_event_id, text=text, created_at=iso(now)
        )
    )
    return int(res.inserted_primary_key[0])


async def tag_media(conn: AsyncConnection, media_id: int, kind: str, **values: str | None) -> bool:
    """動画 (angle / club) か画像 (purpose) に情報を付ける。種類が合わなければ何もせず False。"""
    allowed = {k: v for k, v in values.items() if k in TAGS[kind]}
    res = await conn.execute(
        sa.update(media).where(media.c.id == media_id, media.c.kind == kind).values(**allowed)
    )
    return res.rowcount == 1


async def counts(conn: AsyncConnection, session_id: int) -> dict[str, int]:
    """セッションに入っているもの (取り消したものを除く) の件数。"""
    result: dict[str, int] = {}
    for kind, (table, _) in UNDOABLE.items():
        result[kind] = int(
            (
                await conn.execute(
                    sa.select(sa.func.count()).where(
                        table.c.session_id == session_id, table.c.deleted_at.is_(None)
                    )
                )
            ).scalar_one()
        )
    return result


async def latest(conn: AsyncConnection, user_id: str) -> Entry | None:
    """取り消していないもののうち、いちばん新しいもの。"""
    found: list[Entry] = []
    for kind, (table, label) in UNDOABLE.items():
        row = (
            await conn.execute(
                sa.select(table.c.id, table.c.created_at)
                .join(raw_events, raw_events.c.id == table.c.raw_event_id)
                .where(raw_events.c.user_id == user_id, table.c.deleted_at.is_(None))
                .order_by(table.c.created_at.desc(), table.c.id.desc())
                .limit(1)
            )
        ).first()
        if row:
            found.append(Entry(kind=kind, id=row.id, label=label, created_at=row.created_at))
    return max(found, key=lambda e: (e.created_at, e.id)) if found else None


async def undo(conn: AsyncConnection, entry: Entry, now: datetime) -> None:
    table, _ = UNDOABLE[entry.kind]
    await conn.execute(sa.update(table).where(table.c.id == entry.id).values(deleted_at=iso(now)))
