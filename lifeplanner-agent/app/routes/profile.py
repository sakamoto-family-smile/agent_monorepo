"""/api/profile — 世帯メンバー / 資産 / 負債 の CRUD。

DELETE も必要なので main.py の CORS allow_methods も更新する。
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from repositories.household import ensure_household
from repositories.profile import (
    create_asset,
    create_liability,
    create_member,
    delete_asset,
    delete_liability,
    delete_member,
    list_assets,
    list_liabilities,
    list_members,
)
from services.auth import get_household_id
from services.database import get_session_dep
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/profile", tags=["profile"])


# --- Schemas ------------------------------------------------------------------

Relation = Literal["owner", "spouse", "child", "dependent", "other"]
EmploymentStatus = Literal["employed", "self_employed", "student", "retired", "none"]
AssetKind = Literal["cash", "deposit", "investment", "real_estate", "other"]
LiabilityKind = Literal["mortgage", "car_loan", "credit_card", "student_loan", "other"]


class MemberIn(BaseModel):
    name: str = Field(..., max_length=120)
    relation: Relation
    birth_date: date | None = None
    employment_status: EmploymentStatus = "none"
    annual_income: Decimal = Field(default=Decimal(0), ge=0)
    note: str | None = Field(default=None, max_length=500)


class MemberOut(BaseModel):
    id: int
    household_id: str
    name: str
    relation: str
    birth_date: date | None
    employment_status: str
    annual_income: Decimal
    note: str | None


class AssetIn(BaseModel):
    kind: AssetKind
    name: str = Field(..., max_length=200)
    value: Decimal
    as_of: date
    note: str | None = Field(default=None, max_length=500)


class AssetOut(BaseModel):
    id: int
    household_id: str
    kind: str
    name: str
    value: Decimal
    as_of: date
    note: str | None


class LiabilityIn(BaseModel):
    kind: LiabilityKind
    name: str = Field(..., max_length=200)
    balance: Decimal = Field(..., ge=0)
    interest_rate: Decimal = Field(default=Decimal(0), ge=0, le=1)
    as_of: date
    note: str | None = Field(default=None, max_length=500)


class LiabilityOut(BaseModel):
    id: int
    household_id: str
    kind: str
    name: str
    balance: Decimal
    interest_rate: Decimal
    as_of: date
    note: str | None


# --- Members -----------------------------------------------------------------


@router.get("/members", response_model=list[MemberOut])
async def list_members_endpoint(
    household_id: str = Depends(get_household_id),
    session: AsyncSession = Depends(get_session_dep),
) -> list[MemberOut]:
    await ensure_household(session, household_id, name=household_id)
    items = await list_members(session, household_id)
    return [MemberOut(household_id=m.household_id, **_orm_to_dict(m, MemberOut)) for m in items]


@router.post("/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
async def create_member_endpoint(
    payload: MemberIn,
    household_id: str = Depends(get_household_id),
    session: AsyncSession = Depends(get_session_dep),
) -> MemberOut:
    await ensure_household(session, household_id, name=household_id)
    m = await create_member(session, household_id=household_id, **payload.model_dump())
    await session.commit()
    return MemberOut(household_id=m.household_id, **_orm_to_dict(m, MemberOut))


@router.delete("/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_member_endpoint(
    member_id: int,
    household_id: str = Depends(get_household_id),
    session: AsyncSession = Depends(get_session_dep),
) -> None:
    deleted = await delete_member(session, member_id, household_id)
    if deleted == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    await session.commit()


# --- Assets ------------------------------------------------------------------


@router.get("/assets", response_model=list[AssetOut])
async def list_assets_endpoint(
    household_id: str = Depends(get_household_id),
    session: AsyncSession = Depends(get_session_dep),
) -> list[AssetOut]:
    await ensure_household(session, household_id, name=household_id)
    items = await list_assets(session, household_id)
    return [AssetOut(household_id=a.household_id, **_orm_to_dict(a, AssetOut)) for a in items]


@router.post("/assets", response_model=AssetOut, status_code=status.HTTP_201_CREATED)
async def create_asset_endpoint(
    payload: AssetIn,
    household_id: str = Depends(get_household_id),
    session: AsyncSession = Depends(get_session_dep),
) -> AssetOut:
    await ensure_household(session, household_id, name=household_id)
    obj = await create_asset(session, household_id=household_id, **payload.model_dump())
    await session.commit()
    return AssetOut(household_id=obj.household_id, **_orm_to_dict(obj, AssetOut))


@router.delete("/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset_endpoint(
    asset_id: int,
    household_id: str = Depends(get_household_id),
    session: AsyncSession = Depends(get_session_dep),
) -> None:
    deleted = await delete_asset(session, asset_id, household_id)
    if deleted == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    await session.commit()


# --- Liabilities --------------------------------------------------------------


@router.get("/liabilities", response_model=list[LiabilityOut])
async def list_liabilities_endpoint(
    household_id: str = Depends(get_household_id),
    session: AsyncSession = Depends(get_session_dep),
) -> list[LiabilityOut]:
    await ensure_household(session, household_id, name=household_id)
    items = await list_liabilities(session, household_id)
    return [
        LiabilityOut(household_id=obj.household_id, **_orm_to_dict(obj, LiabilityOut))
        for obj in items
    ]


@router.post("/liabilities", response_model=LiabilityOut, status_code=status.HTTP_201_CREATED)
async def create_liability_endpoint(
    payload: LiabilityIn,
    household_id: str = Depends(get_household_id),
    session: AsyncSession = Depends(get_session_dep),
) -> LiabilityOut:
    await ensure_household(session, household_id, name=household_id)
    obj = await create_liability(session, household_id=household_id, **payload.model_dump())
    await session.commit()
    return LiabilityOut(household_id=obj.household_id, **_orm_to_dict(obj, LiabilityOut))


@router.delete("/liabilities/{liability_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_liability_endpoint(
    liability_id: int,
    household_id: str = Depends(get_household_id),
    session: AsyncSession = Depends(get_session_dep),
) -> None:
    deleted = await delete_liability(session, liability_id, household_id)
    if deleted == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Liability not found")
    await session.commit()


# --- helpers ------------------------------------------------------------------


def _orm_to_dict(obj, schema: type[BaseModel]) -> dict:
    """ORM インスタンスから response schema が求めるフィールドのみ抽出する。

    household_id は個別に渡すので除外済みで返す(重複回避)。
    """
    fields = set(schema.model_fields.keys()) - {"household_id"}
    return {name: getattr(obj, name) for name in fields}
