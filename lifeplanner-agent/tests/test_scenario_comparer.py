"""ScenarioComparer のテスト。"""

from __future__ import annotations

from decimal import Decimal

from agents.event_catalog import BirthEventParams, expand_birth_event
from agents.simulator import (
    HouseholdProfile,
    SimulationAssumptions,
    run_projection,
)
from services.scenario_comparer import compare_scenarios


def _base_projection(events=None):
    profile = HouseholdProfile(
        primary_salary=Decimal(6_000_000),
        spouse_salary=Decimal(3_000_000),
        base_annual_expense=Decimal(4_200_000),
        initial_net_worth=Decimal(5_000_000),
    )
    assumptions = SimulationAssumptions(start_year=2026, horizon_years=30)
    return run_projection(profile, assumptions, events)


def test_compare_with_single_alternative():
    base = _base_projection()
    birth = expand_birth_event(
        BirthEventParams(
            birth_year=2027,
            parental_leave_parent_salary=Decimal(4_800_000),
            household_income_for_childcare=Decimal(9_000_000),
        ),
        horizon_years=30,
    )
    alt = _base_projection(birth)
    report = compare_scenarios(
        base=(1, "baseline", base),
        compares=[(2, "with_child", alt)],
    )
    assert report.base.scenario_id == 1
    assert len(report.compares) == 1
    assert len(report.diffs) == 1
    # 出産ありは純資産が下がる
    assert report.diffs[0].net_worth_diff < Decimal(0)
    # event_net_diff は出産イベントぶん純マイナス
    assert report.diffs[0].event_net_diff < Decimal(0)


def test_compare_with_multiple_alternatives():
    base = _base_projection()
    alt_a = _base_projection()  # 同一条件 → 差分 0
    alt_b = _base_projection(
        expand_birth_event(
            BirthEventParams(birth_year=2027), horizon_years=30
        )
    )
    report = compare_scenarios(
        base=(1, "baseline", base),
        compares=[(2, "clone", alt_a), (3, "with_child", alt_b)],
    )
    assert len(report.compares) == 2
    # alt_a は同一条件なので差分 0
    assert report.diffs[0].net_worth_diff == Decimal(0)
    # alt_b は負
    assert report.diffs[1].net_worth_diff < Decimal(0)


def test_min_max_net_worth_years():
    base = _base_projection()
    report = compare_scenarios(base=(1, "baseline", base), compares=[])
    # 通常シナリオでは初年度が最小(純資産が少ない)、最終年度が最大
    assert report.base.min_net_worth_year <= report.base.max_net_worth_year
    assert report.base.min_net_worth <= report.base.max_net_worth
