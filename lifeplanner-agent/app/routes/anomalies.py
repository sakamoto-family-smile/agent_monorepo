"""/api/anomalies — 支出異常値検出 (月次、canonical カテゴリごと、平均+kσ超え)。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from repositories.household import ensure_household
from services.anomalies import detect_anomalies
from services.auth import get_household_id
from services.database import get_session_dep
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api", tags=["anomalies"])


class AnomalyOut(BaseModel):
    year_month: str
    canonical_category: str
    expense: Decimal
    mean: Decimal
    std: Decimal
    z_score: Decimal
    threshold: Decimal


class AnomaliesResponse(BaseModel):
    household_id: str
    target_month: date
    history_months: int
    k: Decimal
    anomalies: list[AnomalyOut]


@router.get("/anomalies", response_model=AnomaliesResponse)
async def anomalies_endpoint(
    target_month: date | None = Query(default=None, description="判定対象月 (既定: 今月)"),
    history_months: int = Query(default=6, ge=1, le=24),
    k: Decimal = Query(default=Decimal("3"), ge=Decimal("1"), le=Decimal("5")),
    household_id: str = Depends(get_household_id),
    session: AsyncSession = Depends(get_session_dep),
) -> AnomaliesResponse:
    await ensure_household(session, household_id, name=household_id)
    target = target_month or date.today().replace(day=1)
    anomalies = await detect_anomalies(
        session,
        household_id,
        target_month=target,
        history_months=history_months,
        k=k,
    )
    return AnomaliesResponse(
        household_id=household_id,
        target_month=target,
        history_months=history_months,
        k=k,
        anomalies=[AnomalyOut(**a.__dict__) for a in anomalies],
    )
