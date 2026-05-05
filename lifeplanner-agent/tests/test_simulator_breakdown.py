"""PR 1: simulator のカテゴリ別 / イベント別 breakdown 出力テスト。

- expense_breakdown は inflation 適用後にカテゴリ単位で正しく出る
- event_breakdown は CashFlowDelta 1 行 = 1 line item で出る
- 後方互換: expense_baseline_by_category=None なら旧挙動
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from agents.event_catalog import BirthEventParams, expand_birth_event
from agents.event_catalog.types import EventCategory
from agents.simulator import (
    HouseholdProfile,
    SimulationAssumptions,
    run_projection,
)


@pytest.fixture
def assumptions_3years() -> SimulationAssumptions:
    """短期 (3 年) で挙動を検証しやすくする。"""
    return SimulationAssumptions(
        start_year=2026,
        horizon_years=3,
        salary_growth_rate=Decimal("0.00"),
        inflation_rate=Decimal("0.10"),  # 大き目の inflation で動きを見やすく
        investment_return_rate=Decimal("0.00"),
    )


# ---- expense_breakdown ----


def test_expense_breakdown_uses_baseline_when_provided(assumptions_3years):
    """`expense_baseline_by_category` を渡すと breakdown がカテゴリ別に出る。"""
    profile = HouseholdProfile(
        primary_salary=Decimal(5_000_000),
        expense_baseline_by_category={
            "food": Decimal(600_000),
            "housing": Decimal(1_200_000),
            "communication": Decimal(240_000),
        },
    )
    result = run_projection(profile, assumptions_3years)
    row0 = result.rows[0]
    # 1 年目は inflation 0 回適用なので baseline と一致
    assert row0.expense_breakdown == {
        "food": Decimal(600_000),
        "housing": Decimal(1_200_000),
        "communication": Decimal(240_000),
    }
    # living_expense は breakdown の合計と一致
    assert row0.living_expense == sum(row0.expense_breakdown.values())


def test_expense_breakdown_inflates_per_year(assumptions_3years):
    """カテゴリ別 inflation は単一 inflation_rate で全カテゴリに適用される。"""
    profile = HouseholdProfile(
        primary_salary=Decimal(5_000_000),
        expense_baseline_by_category={"food": Decimal(1_000_000)},
    )
    result = run_projection(profile, assumptions_3years)
    # 1.10 ^ 0, ^1, ^2
    assert result.rows[0].expense_breakdown["food"] == Decimal(1_000_000)
    assert result.rows[1].expense_breakdown["food"] == Decimal("1100000.00")
    assert result.rows[2].expense_breakdown["food"] == Decimal("1210000.0000")


def test_expense_breakdown_falls_back_to_other_category(assumptions_3years):
    """expense_baseline_by_category=None なら base_annual_expense を 'other' に集約。"""
    profile = HouseholdProfile(
        primary_salary=Decimal(5_000_000),
        base_annual_expense=Decimal(3_600_000),
    )
    result = run_projection(profile, assumptions_3years)
    row0 = result.rows[0]
    assert list(row0.expense_breakdown.keys()) == ["other"]
    assert row0.expense_breakdown["other"] == Decimal(3_600_000)
    assert row0.living_expense == Decimal(3_600_000)


def test_living_expense_equals_breakdown_sum_every_year(assumptions_3years):
    profile = HouseholdProfile(
        primary_salary=Decimal(5_000_000),
        expense_baseline_by_category={
            "food": Decimal(720_000),
            "housing": Decimal(1_500_000),
        },
    )
    result = run_projection(profile, assumptions_3years)
    for row in result.rows:
        assert row.living_expense == sum(row.expense_breakdown.values())


# ---- event_breakdown ----


def test_event_breakdown_lists_birth_event_lines():
    """E01 出産で year ごとに複数 line item が出る (児童手当・保育料・育休給付等)。"""
    profile = HouseholdProfile(
        primary_salary=Decimal(6_000_000),
        expense_baseline_by_category={"other": Decimal(3_000_000)},
    )
    assumptions = SimulationAssumptions(
        start_year=2026,
        horizon_years=5,
        salary_growth_rate=Decimal("0.00"),
        inflation_rate=Decimal("0.00"),
        investment_return_rate=Decimal("0.00"),
    )
    birth = BirthEventParams(
        birth_year=2026,
        university_track="national_public",
        use_childcare=True,
        parental_leave_parent_salary=Decimal(4_000_000),
        parental_leave_months=12,
        household_income_for_childcare=Decimal(7_000_000),
    )
    deltas = expand_birth_event(birth, horizon_years=5)
    # scenario_runner 相当: event_type="E01" を付与
    deltas_with_type = [replace(d, event_type="E01") for d in deltas]

    result = run_projection(profile, assumptions, deltas_with_type)

    # 出産年は出産費用 + 育休給付 + 児童手当 + 保育料 等で複数 line
    row_2026 = next(r for r in result.rows if r.year == 2026)
    assert len(row_2026.event_breakdown) >= 2
    for line in row_2026.event_breakdown:
        assert line.event_type == "E01"
        assert line.label  # ラベルが空でない
        assert line.category in {c.value for c in EventCategory}

    # event_net == sum(breakdown.amount)
    for row in result.rows:
        assert row.event_net == sum(
            (line.amount for line in row.event_breakdown), Decimal(0)
        )


def test_event_breakdown_empty_when_no_events(assumptions_3years):
    profile = HouseholdProfile(
        primary_salary=Decimal(5_000_000),
        expense_baseline_by_category={"other": Decimal(3_000_000)},
    )
    result = run_projection(profile, assumptions_3years)
    for row in result.rows:
        assert row.event_breakdown == []
        assert row.event_net == Decimal(0)


def test_event_breakdown_unset_event_type_falls_back():
    """event_type が空の CashFlowDelta は '?' で出力 (catalog バグ検知用)。"""
    from agents.event_catalog.types import CashFlowDelta

    profile = HouseholdProfile(
        primary_salary=Decimal(5_000_000),
        expense_baseline_by_category={"other": Decimal(3_000_000)},
    )
    assumptions = SimulationAssumptions(
        start_year=2026,
        horizon_years=2,
        salary_growth_rate=Decimal("0.00"),
        inflation_rate=Decimal("0.00"),
        investment_return_rate=Decimal("0.00"),
    )
    deltas = [
        CashFlowDelta(
            year=2026,
            amount=Decimal(-500_000),
            category=EventCategory.ONE_TIME,
            label="未分類イベント",
            # event_type 未設定 (default "")
        )
    ]
    result = run_projection(profile, assumptions, deltas)
    line = result.rows[0].event_breakdown[0]
    assert line.event_type == "?"


# ---- to_dict (API serialization) ----


def test_to_dict_includes_breakdowns():
    """to_dict() で expense_breakdown / event_breakdown が JSON 化される。"""
    profile = HouseholdProfile(
        primary_salary=Decimal(5_000_000),
        expense_baseline_by_category={
            "food": Decimal(600_000),
            "housing": Decimal(1_200_000),
        },
    )
    assumptions = SimulationAssumptions(
        start_year=2026,
        horizon_years=2,
        salary_growth_rate=Decimal("0.00"),
        inflation_rate=Decimal("0.00"),
        investment_return_rate=Decimal("0.00"),
    )
    result = run_projection(profile, assumptions)
    d = result.to_dict()
    row = d["rows"][0]
    assert "expense_breakdown" in row
    assert row["expense_breakdown"] == {"food": "600000", "housing": "1200000"}
    assert "event_breakdown" in row
    assert row["event_breakdown"] == []
    # 既存フィールドも残っている
    assert "living_expense" in row
    assert "event_net" in row
