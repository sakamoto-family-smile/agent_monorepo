"""Scenario / LifeEvent / SimulationResultRow の CRUD。"""

from __future__ import annotations

from models.db import LifeEvent, Scenario, SimulationResultRow
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


async def list_scenarios(session: AsyncSession, household_id: str) -> list[Scenario]:
    result = await session.execute(
        select(Scenario).where(Scenario.household_id == household_id).order_by(Scenario.id)
    )
    return list(result.scalars().all())


async def get_scenario(session: AsyncSession, scenario_id: int) -> Scenario | None:
    result = await session.execute(select(Scenario).where(Scenario.id == scenario_id))
    return result.scalar_one_or_none()


async def get_scenario_for_household(
    session: AsyncSession, scenario_id: int, household_id: str
) -> Scenario | None:
    result = await session.execute(
        select(Scenario)
        .where(Scenario.id == scenario_id)
        .where(Scenario.household_id == household_id)
    )
    return result.scalar_one_or_none()


async def create_scenario(
    session: AsyncSession,
    *,
    household_id: str,
    name: str,
    description: str | None,
    base_assumptions: dict,
) -> Scenario:
    scenario = Scenario(
        household_id=household_id,
        name=name,
        description=description,
        base_assumptions=base_assumptions,
    )
    session.add(scenario)
    await session.flush()
    return scenario


async def delete_scenario(session: AsyncSession, scenario_id: int) -> None:
    await session.execute(delete(Scenario).where(Scenario.id == scenario_id))


async def list_events(session: AsyncSession, scenario_id: int) -> list[LifeEvent]:
    result = await session.execute(
        select(LifeEvent)
        .where(LifeEvent.scenario_id == scenario_id)
        .order_by(LifeEvent.start_year)
    )
    return list(result.scalars().all())


async def add_event(
    session: AsyncSession,
    *,
    scenario_id: int,
    event_type: str,
    start_year: int,
    params: dict,
) -> LifeEvent:
    event = LifeEvent(
        scenario_id=scenario_id,
        event_type=event_type,
        start_year=start_year,
        params=params,
    )
    session.add(event)
    await session.flush()
    return event


async def replace_simulation_results(
    session: AsyncSession,
    *,
    scenario_id: int,
    rows: list[dict],
) -> None:
    """シミュ結果を全入れ替え。rows は {year, metrics} のリスト。"""
    await session.execute(
        delete(SimulationResultRow).where(SimulationResultRow.scenario_id == scenario_id)
    )
    for r in rows:
        session.add(
            SimulationResultRow(
                scenario_id=scenario_id,
                year=r["year"],
                metrics=r["metrics"],
            )
        )
    await session.flush()


async def list_results(session: AsyncSession, scenario_id: int) -> list[SimulationResultRow]:
    result = await session.execute(
        select(SimulationResultRow)
        .where(SimulationResultRow.scenario_id == scenario_id)
        .order_by(SimulationResultRow.year)
    )
    return list(result.scalars().all())
