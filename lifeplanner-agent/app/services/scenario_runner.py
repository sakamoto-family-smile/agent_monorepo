"""シナリオ DB レコード → Simulator 実行 → 結果永続化のオーケストレーション。"""

from __future__ import annotations

from decimal import Decimal

from agents.event_catalog import BirthEventParams, expand_birth_event
from agents.event_catalog.types import CashFlowDelta
from agents.simulator import (
    HouseholdProfile,
    SimulationAssumptions,
    SimulationResult,
    run_projection,
)
from models.db import LifeEvent, Scenario
from repositories.scenario import list_events, replace_simulation_results
from sqlalchemy.ext.asyncio import AsyncSession


def _dec(v, default: Decimal = Decimal(0)) -> Decimal:
    if v is None:
        return default
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def _build_profile(assumptions: dict) -> HouseholdProfile:
    return HouseholdProfile(
        primary_salary=_dec(assumptions.get("primary_salary")),
        spouse_salary=_dec(assumptions.get("spouse_salary")),
        base_annual_expense=_dec(assumptions.get("base_annual_expense", 3_600_000)),
        initial_net_worth=_dec(assumptions.get("initial_net_worth")),
    )


def _build_assumptions(a: dict) -> SimulationAssumptions:
    return SimulationAssumptions(
        start_year=int(a["start_year"]),
        horizon_years=int(a.get("horizon_years", 30)),
        salary_growth_rate=_dec(a.get("salary_growth_rate", "0.01")),
        inflation_rate=_dec(a.get("inflation_rate", "0.01")),
        investment_return_rate=_dec(a.get("investment_return_rate", "0.02")),
        tax_year=int(a["tax_year"]) if a.get("tax_year") is not None else None,
    )


def _expand_birth_params(params: dict, start_year: int) -> BirthEventParams:
    return BirthEventParams(
        birth_year=int(params.get("birth_year", start_year)),
        is_third_or_later=bool(params.get("is_third_or_later", False)),
        elementary_private=bool(params.get("elementary_private", False)),
        junior_high_private=bool(params.get("junior_high_private", False)),
        high_school_private=bool(params.get("high_school_private", False)),
        university_track=params.get("university_track", "national_public"),
        use_childcare=bool(params.get("use_childcare", True)),
        parental_leave_parent_salary=_dec(params.get("parental_leave_parent_salary", 0)),
        parental_leave_months=params.get("parental_leave_months"),
        household_income_for_childcare=_dec(
            params.get("household_income_for_childcare", 5_000_000)
        ),
    )


def _expand_events(events: list[LifeEvent], horizon_years: int) -> list[CashFlowDelta]:
    """全イベントを CashFlowDelta 列に展開する。"""
    deltas: list[CashFlowDelta] = []
    for e in events:
        if e.event_type == "E01":
            params = _expand_birth_params(e.params, e.start_year)
            deltas.extend(expand_birth_event(params, horizon_years=horizon_years))
        else:
            # Phase 2 スコープ外。将来の EventCatalog 拡張で追加。
            continue
    return deltas


async def simulate_scenario(
    session: AsyncSession, scenario: Scenario
) -> SimulationResult:
    """シナリオをロード → シミュ → DB に結果を保存し SimulationResult を返す。"""
    assumptions_raw = scenario.base_assumptions or {}
    profile = _build_profile(assumptions_raw)
    assumptions = _build_assumptions(assumptions_raw)
    events = await list_events(session, scenario.id)
    deltas = _expand_events(events, assumptions.horizon_years)

    result = run_projection(profile, assumptions, deltas)

    rows_payload = [
        {
            "year": row.year,
            "metrics": {k: str(v) if isinstance(v, Decimal) else v for k, v in row.__dict__.items()},
        }
        for row in result.rows
    ]
    await replace_simulation_results(session, scenario_id=scenario.id, rows=rows_payload)
    await session.commit()
    return result
