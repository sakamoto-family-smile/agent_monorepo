"""LINE userId ↔ household の紐付けを扱う CRUD。"""

from __future__ import annotations

from models.db import LineUserLink
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


async def get_link(session: AsyncSession, line_user_id: str) -> LineUserLink | None:
    result = await session.execute(
        select(LineUserLink).where(LineUserLink.line_user_id == line_user_id)
    )
    return result.scalar_one_or_none()


async def create_link(
    session: AsyncSession, *, line_user_id: str, household_id: str
) -> LineUserLink:
    link = LineUserLink(line_user_id=line_user_id, household_id=household_id)
    session.add(link)
    await session.flush()
    return link


async def delete_link(session: AsyncSession, line_user_id: str) -> bool:
    """存在すれば削除。削除したら True。"""
    result = await session.execute(
        delete(LineUserLink).where(LineUserLink.line_user_id == line_user_id)
    )
    return (result.rowcount or 0) > 0
