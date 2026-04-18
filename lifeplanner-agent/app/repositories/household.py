"""Household の CRUD。Phase 1 は最小機能（取得・UPSERT）のみ。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Household


async def get_household(session: AsyncSession, household_id: str) -> Household | None:
    result = await session.execute(select(Household).where(Household.id == household_id))
    return result.scalar_one_or_none()


async def ensure_household(
    session: AsyncSession,
    household_id: str,
    *,
    name: str | None = None,
) -> Household:
    """指定 ID が無ければ作成して返す。ある場合は取得のみ。"""
    existing = await get_household(session, household_id)
    if existing is not None:
        return existing

    household = Household(id=household_id, name=name or household_id)
    session.add(household)
    await session.flush()
    return household
