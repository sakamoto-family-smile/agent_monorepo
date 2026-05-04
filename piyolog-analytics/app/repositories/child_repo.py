"""Phase 4-B: 子情報の永続化 (家族ごとの子の生年月日 / 名前)。

EventRepo / SessionRepo と engine を共有する想定。LINE 設定 UI から
upsert され、context_builder が読み出す。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from .models import ChildRow

logger = logging.getLogger(__name__)


_BIRTH_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# 表示崩れを避けるための簡易バリデーション。emoji や改行は弾く。
_NAME_RE = re.compile(r"^[^\r\n\t]{1,32}$")


@dataclass(frozen=True)
class Child:
    family_id: str
    child_id: str
    birth_date: str | None
    name: str | None
    updated_at: str


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def is_valid_birth_date(value: str) -> bool:
    """LINE datetime picker (mode=date) から来る `YYYY-MM-DD` を検証。"""
    if not _BIRTH_DATE_RE.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def is_valid_name(value: str) -> bool:
    return bool(_NAME_RE.match(value))


class ChildRepo:
    """ChildRow の薄いラッパ。

    `ChildRepo(engine=event_repo.engine)` で生成する。
    """

    def __init__(self, *, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def get(self, *, family_id: str, child_id: str) -> Child | None:
        async with self._sessionmaker() as session:
            stmt = select(ChildRow).where(
                ChildRow.family_id == family_id,
                ChildRow.child_id == child_id,
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            return _to_child(row) if row else None

    async def upsert_birth_date(
        self, *, family_id: str, child_id: str, birth_date: str
    ) -> Child:
        if not is_valid_birth_date(birth_date):
            raise ValueError(f"invalid birth_date: {birth_date!r}")
        return await self._upsert(
            family_id=family_id, child_id=child_id, birth_date=birth_date
        )

    async def upsert_name(self, *, family_id: str, child_id: str, name: str) -> Child:
        if not is_valid_name(name):
            raise ValueError(f"invalid name: {name!r}")
        return await self._upsert(family_id=family_id, child_id=child_id, name=name)

    async def _upsert(
        self,
        *,
        family_id: str,
        child_id: str,
        birth_date: str | None = None,
        name: str | None = None,
    ) -> Child:
        now = _now_iso()
        async with self._sessionmaker() as session:
            existing = (
                await session.execute(
                    select(ChildRow).where(
                        ChildRow.family_id == family_id,
                        ChildRow.child_id == child_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                row = ChildRow(
                    family_id=family_id,
                    child_id=child_id,
                    birth_date=birth_date,
                    name=name,
                    updated_at=now,
                )
                session.add(row)
            else:
                if birth_date is not None:
                    existing.birth_date = birth_date
                if name is not None:
                    existing.name = name
                existing.updated_at = now
                row = existing
            await session.commit()
            await session.refresh(row)
            return _to_child(row)


def _to_child(row: ChildRow) -> Child:
    return Child(
        family_id=row.family_id,
        child_id=row.child_id,
        birth_date=row.birth_date,
        name=row.name,
        updated_at=row.updated_at,
    )


__all__ = ["Child", "ChildRepo", "is_valid_birth_date", "is_valid_name"]
