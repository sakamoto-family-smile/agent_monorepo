"""世帯プロファイル (HouseholdMember / Asset / Liability) の CRUD。"""

from __future__ import annotations

from models.db import Asset, HouseholdMember, Liability
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

# --- HouseholdMember ----------------------------------------------------------


async def list_members(session: AsyncSession, household_id: str) -> list[HouseholdMember]:
    result = await session.execute(
        select(HouseholdMember)
        .where(HouseholdMember.household_id == household_id)
        .order_by(HouseholdMember.id)
    )
    return list(result.scalars().all())


async def create_member(session: AsyncSession, **fields) -> HouseholdMember:
    obj = HouseholdMember(**fields)
    session.add(obj)
    await session.flush()
    return obj


async def delete_member(session: AsyncSession, member_id: int, household_id: str) -> int:
    """指定メンバーを削除。削除件数を返す (0/1)。"""
    r = await session.execute(
        delete(HouseholdMember)
        .where(HouseholdMember.id == member_id)
        .where(HouseholdMember.household_id == household_id)
    )
    return r.rowcount or 0


# --- Asset --------------------------------------------------------------------


async def list_assets(session: AsyncSession, household_id: str) -> list[Asset]:
    result = await session.execute(
        select(Asset).where(Asset.household_id == household_id).order_by(Asset.id)
    )
    return list(result.scalars().all())


async def create_asset(session: AsyncSession, **fields) -> Asset:
    obj = Asset(**fields)
    session.add(obj)
    await session.flush()
    return obj


async def delete_asset(session: AsyncSession, asset_id: int, household_id: str) -> int:
    r = await session.execute(
        delete(Asset)
        .where(Asset.id == asset_id)
        .where(Asset.household_id == household_id)
    )
    return r.rowcount or 0


# --- Liability ----------------------------------------------------------------


async def list_liabilities(session: AsyncSession, household_id: str) -> list[Liability]:
    result = await session.execute(
        select(Liability)
        .where(Liability.household_id == household_id)
        .order_by(Liability.id)
    )
    return list(result.scalars().all())


async def create_liability(session: AsyncSession, **fields) -> Liability:
    obj = Liability(**fields)
    session.add(obj)
    await session.flush()
    return obj


async def delete_liability(session: AsyncSession, liability_id: int, household_id: str) -> int:
    r = await session.execute(
        delete(Liability)
        .where(Liability.id == liability_id)
        .where(Liability.household_id == household_id)
    )
    return r.rowcount or 0
