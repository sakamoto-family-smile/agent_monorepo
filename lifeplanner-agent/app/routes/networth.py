"""/api/networth — 純資産サマリ。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from repositories.household import ensure_household
from services.auth import get_household_id
from services.database import get_session_dep
from services.networth import compute_networth
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api", tags=["networth"])


class NetWorthResponse(BaseModel):
    household_id: str
    as_of: date
    total_assets: Decimal
    total_liabilities: Decimal
    net_worth: Decimal
    by_kind_assets: dict[str, Decimal]
    by_kind_liabilities: dict[str, Decimal]


@router.get("/networth", response_model=NetWorthResponse)
async def networth_endpoint(
    as_of: date | None = Query(default=None),
    household_id: str = Depends(get_household_id),
    session: AsyncSession = Depends(get_session_dep),
) -> NetWorthResponse:
    await ensure_household(session, household_id, name=household_id)
    s = await compute_networth(session, household_id, as_of=as_of)
    return NetWorthResponse(
        household_id=s.household_id,
        as_of=s.current.as_of,
        total_assets=s.current.total_assets,
        total_liabilities=s.current.total_liabilities,
        net_worth=s.current.net_worth,
        by_kind_assets=s.by_kind_assets,
        by_kind_liabilities=s.by_kind_liabilities,
    )
