"""/api/scenarios — シナリオ CRUD とイベント追加 API。"""

from __future__ import annotations

import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from repositories.household import ensure_household
from repositories.scenario import (
    add_event,
    create_scenario,
    get_scenario_for_household,
    list_events,
    list_scenarios,
)
from services.auth import get_household_id
from services.database import get_session_dep
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


# -- Request / Response schemas ---------------------------------------------


class ScenarioCreateIn(BaseModel):
    name: str = Field(..., max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    # HouseholdProfile + SimulationAssumptions をまとめて受ける(Phase 2 簡易)
    primary_salary: Decimal = Field(..., ge=0)
    spouse_salary: Decimal = Field(default=Decimal(0), ge=0)
    base_annual_expense: Decimal = Field(default=Decimal(3_600_000), ge=0)
    initial_net_worth: Decimal = Field(default=Decimal(0))
    start_year: int = Field(..., ge=2000, le=2100)
    horizon_years: int = Field(default=30, ge=1, le=50)
    salary_growth_rate: Decimal = Field(default=Decimal("0.01"))
    inflation_rate: Decimal = Field(default=Decimal("0.01"))
    investment_return_rate: Decimal = Field(default=Decimal("0.02"))
    tax_year: int | None = Field(default=None)


class ScenarioOut(BaseModel):
    id: int
    household_id: str
    name: str
    description: str | None
    base_assumptions: dict


class EventCreateIn(BaseModel):
    event_type: str = Field(..., pattern=r"^E\d{2}$")  # E01, E02, ...
    start_year: int = Field(..., ge=2000, le=2100)
    params: dict = Field(default_factory=dict)


class EventOut(BaseModel):
    id: int
    scenario_id: int
    event_type: str
    start_year: int
    params: dict


# -- Helpers -----------------------------------------------------------------


def _assumptions_to_dict(payload: ScenarioCreateIn) -> dict:
    """Pydantic (Decimal) -> dict (str) で JSON 永続化。"""
    d = payload.model_dump()
    d.pop("name", None)
    d.pop("description", None)
    # Decimal は str に寄せる(JSON 型は Decimal を直接扱えない)
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in d.items()}


# -- Endpoints ---------------------------------------------------------------


@router.get("", response_model=list[ScenarioOut])
async def list_scenarios_endpoint(
    household_id: str = Depends(get_household_id),
    session: AsyncSession = Depends(get_session_dep),
) -> list[ScenarioOut]:
    await ensure_household(session, household_id, name=household_id)
    items = await list_scenarios(session, household_id)
    return [
        ScenarioOut(
            id=s.id,
            household_id=s.household_id,
            name=s.name,
            description=s.description,
            base_assumptions=s.base_assumptions,
        )
        for s in items
    ]


@router.post("", response_model=ScenarioOut, status_code=status.HTTP_201_CREATED)
async def create_scenario_endpoint(
    payload: ScenarioCreateIn,
    household_id: str = Depends(get_household_id),
    session: AsyncSession = Depends(get_session_dep),
) -> ScenarioOut:
    await ensure_household(session, household_id, name=household_id)
    scenario = await create_scenario(
        session,
        household_id=household_id,
        name=payload.name,
        description=payload.description,
        base_assumptions=_assumptions_to_dict(payload),
    )
    await session.commit()
    logger.info("Scenario created: id=%d household=%s", scenario.id, household_id)

    from instrumentation import emit_business

    emit_business(
        domain="scenario",
        action="scenario_created",
        resource_type="scenario",
        resource_id=str(scenario.id),
        attributes={
            "name": scenario.name,
            "has_description": scenario.description is not None,
        },
        user_id=household_id,
    )

    return ScenarioOut(
        id=scenario.id,
        household_id=scenario.household_id,
        name=scenario.name,
        description=scenario.description,
        base_assumptions=scenario.base_assumptions,
    )


@router.get("/{scenario_id}", response_model=ScenarioOut)
async def get_scenario_endpoint(
    scenario_id: int,
    household_id: str = Depends(get_household_id),
    session: AsyncSession = Depends(get_session_dep),
) -> ScenarioOut:
    scenario = await get_scenario_for_household(session, scenario_id, household_id)
    if scenario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")
    return ScenarioOut(
        id=scenario.id,
        household_id=scenario.household_id,
        name=scenario.name,
        description=scenario.description,
        base_assumptions=scenario.base_assumptions,
    )


@router.post("/{scenario_id}/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def add_event_endpoint(
    scenario_id: int,
    payload: EventCreateIn,
    household_id: str = Depends(get_household_id),
    session: AsyncSession = Depends(get_session_dep),
) -> EventOut:
    scenario = await get_scenario_for_household(session, scenario_id, household_id)
    if scenario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")
    event = await add_event(
        session,
        scenario_id=scenario_id,
        event_type=payload.event_type,
        start_year=payload.start_year,
        params=payload.params,
    )
    await session.commit()
    return EventOut(
        id=event.id,
        scenario_id=event.scenario_id,
        event_type=event.event_type,
        start_year=event.start_year,
        params=event.params,
    )


class CompareIn(BaseModel):
    base_scenario_id: int
    compare_scenario_ids: list[int] = Field(default_factory=list, min_length=1)


class SummaryOut(BaseModel):
    scenario_id: int
    name: str
    horizon_years: int
    total_net_worth_end: Decimal
    total_take_home: Decimal
    total_tax_paid: Decimal
    total_social_insurance: Decimal
    total_event_net: Decimal
    min_net_worth: Decimal
    min_net_worth_year: int
    max_net_worth: Decimal
    max_net_worth_year: int


class DiffOut(BaseModel):
    scenario_id: int
    name: str
    net_worth_diff: Decimal
    event_net_diff: Decimal
    take_home_diff: Decimal
    tax_diff: Decimal


class CompareOut(BaseModel):
    base: SummaryOut
    compares: list[SummaryOut]
    diffs: list[DiffOut]


@router.post("/compare", response_model=CompareOut)
async def compare_scenarios_endpoint(
    payload: CompareIn,
    household_id: str = Depends(get_household_id),
    session: AsyncSession = Depends(get_session_dep),
) -> CompareOut:
    from services.scenario_comparer import compare_scenarios
    from services.scenario_runner import simulate_scenario

    base = await get_scenario_for_household(session, payload.base_scenario_id, household_id)
    if base is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Base scenario not found: {payload.base_scenario_id}",
        )
    base_result = await simulate_scenario(session, base)

    compare_loaded: list[tuple[int, str, object]] = []
    for sid in payload.compare_scenario_ids:
        s = await get_scenario_for_household(session, sid, household_id)
        if s is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Compare scenario not found: {sid}",
            )
        r = await simulate_scenario(session, s)
        compare_loaded.append((s.id, s.name, r))

    report = compare_scenarios(
        base=(base.id, base.name, base_result),
        compares=compare_loaded,  # type: ignore[arg-type]
    )
    return CompareOut(
        base=SummaryOut(**report.base.__dict__),
        compares=[SummaryOut(**s.__dict__) for s in report.compares],
        diffs=[DiffOut(**d.__dict__) for d in report.diffs],
    )


@router.get("/{scenario_id}/events", response_model=list[EventOut])
async def list_events_endpoint(
    scenario_id: int,
    household_id: str = Depends(get_household_id),
    session: AsyncSession = Depends(get_session_dep),
) -> list[EventOut]:
    scenario = await get_scenario_for_household(session, scenario_id, household_id)
    if scenario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")
    events = await list_events(session, scenario_id)
    return [
        EventOut(
            id=e.id,
            scenario_id=e.scenario_id,
            event_type=e.event_type,
            start_year=e.start_year,
            params=e.params,
        )
        for e in events
    ]
