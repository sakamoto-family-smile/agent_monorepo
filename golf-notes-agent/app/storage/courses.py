"""コース名。表記ゆれ (全角・半角・空白・「カントリー倶楽部」の略し方など) を 1 つのコースにまとめる。

同じとみなすのは、正規化 (NFKC・空白を除く・小文字) した名前が、名前か別名のどれかと一致するとき。
別名は送った表記をそのまま aliases_json に足していく。
"""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.storage.tables import courses, sessions

MAX_NAME = 60


@dataclass(frozen=True)
class Course:
    id: int
    name: str


def normalize(name: str) -> str:
    return "".join(unicodedata.normalize("NFKC", name).split()).lower()


async def find_or_create(conn: AsyncConnection, name: str) -> Course:
    name = " ".join(name.split())[:MAX_NAME]
    key = normalize(name)
    for row in (await conn.execute(sa.select(courses))).all():
        aliases = json.loads(row.aliases_json)
        if key in {normalize(row.name), *map(normalize, aliases)}:
            if name != row.name and name not in aliases:
                await conn.execute(
                    sa.update(courses)
                    .where(courses.c.id == row.id)
                    .values(aliases_json=json.dumps([*aliases, name], ensure_ascii=False))
                )
            return Course(id=row.id, name=row.name)
    res = await conn.execute(sa.insert(courses).values(name=name, aliases_json="[]"))
    return Course(id=int(res.inserted_primary_key[0]), name=name)


async def get(conn: AsyncConnection, course_id: int) -> Course | None:
    row = (await conn.execute(sa.select(courses).where(courses.c.id == course_id))).first()
    return Course(id=row.id, name=row.name) if row else None


async def recent(conn: AsyncConnection, limit: int = 10) -> list[Course]:
    """最近のラウンドで使ったコース (新しい順)。"""
    last_used = sa.func.max(sessions.c.started_at).label("last_used")
    rows = (
        await conn.execute(
            sa.select(courses.c.id, courses.c.name, last_used)
            .join(sessions, sessions.c.course_id == courses.c.id)
            .group_by(courses.c.id)
            .order_by(last_used.desc())
            .limit(limit)
        )
    ).all()
    return [Course(id=r.id, name=r.name) for r in rows]
