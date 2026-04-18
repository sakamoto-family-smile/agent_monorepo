"""/api/scenarios/{id}/simulate — シナリオ実行と結果返却。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from repositories.scenario import get_scenario_for_household
from services.auth import get_household_id
from services.database import get_session_dep
from services.scenario_runner import simulate_scenario
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scenarios", tags=["simulate"])


class YearMetricsOut(BaseModel):
    """1 年分のシミュレーション結果。Decimal は str で返却。"""

    year: int
    gross_income: str
    social_insurance: str
    income_tax: str
    resident_tax: str
    take_home: str
    living_expense: str
    event_net: str
    annual_net: str
    investment_gain: str
    net_worth_end: str


class SimulationOut(BaseModel):
    scenario_id: int
    horizon_years: int
    rows: list[YearMetricsOut]
    total_net_worth_end: str
    total_take_home: str
    total_tax_paid: str
    total_social_insurance: str
    total_event_net: str


@router.post("/{scenario_id}/simulate", response_model=SimulationOut)
async def simulate_endpoint(
    scenario_id: int,
    household_id: str = Depends(get_household_id),
    session: AsyncSession = Depends(get_session_dep),
) -> SimulationOut:
    scenario = await get_scenario_for_household(session, scenario_id, household_id)
    if scenario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")

    result = await simulate_scenario(session, scenario)
    logger.info(
        "Simulation completed: scenario=%d horizon=%d",
        scenario_id, len(result.rows),
    )

    return SimulationOut(
        scenario_id=scenario_id,
        horizon_years=len(result.rows),
        rows=[
            YearMetricsOut(
                year=row.year,
                gross_income=str(row.gross_income),
                social_insurance=str(row.social_insurance),
                income_tax=str(row.income_tax),
                resident_tax=str(row.resident_tax),
                take_home=str(row.take_home),
                living_expense=str(row.living_expense),
                event_net=str(row.event_net),
                annual_net=str(row.annual_net),
                investment_gain=str(row.investment_gain),
                net_worth_end=str(row.net_worth_end),
            )
            for row in result.rows
        ],
        total_net_worth_end=str(result.total_net_worth_end),
        total_take_home=str(result.total_take_home),
        total_tax_paid=str(result.total_tax_paid),
        total_social_insurance=str(result.total_social_insurance),
        total_event_net=str(result.total_event_net),
    )
