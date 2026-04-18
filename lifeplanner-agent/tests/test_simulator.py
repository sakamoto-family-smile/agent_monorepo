"""Simulator の 30 年プロジェクションテスト。"""

from __future__ import annotations

from decimal import Decimal

import pytest
from agents.event_catalog import BirthEventParams, expand_birth_event
from agents.simulator import (
    HouseholdProfile,
    SimulationAssumptions,
    run_projection,
)


@pytest.fixture
def base_profile() -> HouseholdProfile:
    return HouseholdProfile(
        primary_salary=Decimal(6_000_000),
        spouse_salary=Decimal(3_000_000),
        base_annual_expense=Decimal(4_200_000),
        initial_net_worth=Decimal(5_000_000),
    )


@pytest.fixture
def base_assumptions() -> SimulationAssumptions:
    return SimulationAssumptions(
        start_year=2026,
        horizon_years=30,
        salary_growth_rate=Decimal("0.01"),
        inflation_rate=Decimal("0.01"),
        investment_return_rate=Decimal("0.02"),
    )


def test_projection_produces_horizon_rows(base_profile, base_assumptions):
    result = run_projection(base_profile, base_assumptions)
    assert len(result.rows) == 30
    assert result.rows[0].year == 2026
    assert result.rows[-1].year == 2055


def test_projection_without_events_is_positive_growth(base_profile, base_assumptions):
    """イベントなしで 30 年回すと純資産は増える(手取 > 生活費)。"""
    result = run_projection(base_profile, base_assumptions)
    assert result.total_net_worth_end > base_profile.initial_net_worth
    assert result.total_take_home > 0
    assert result.total_tax_paid > 0
    assert result.total_event_net == Decimal(0)


def test_salary_grows_each_year(base_profile, base_assumptions):
    result = run_projection(base_profile, base_assumptions)
    # 給与上昇率 1% で単調増加
    for i in range(1, 30):
        assert result.rows[i].gross_income > result.rows[i - 1].gross_income


def test_birth_event_reduces_net_worth(base_profile, base_assumptions):
    """出産イベントを入れると純資産は下がる(教育費等の累積 > 児童手当)。"""
    base = run_projection(base_profile, base_assumptions)
    birth_params = BirthEventParams(
        birth_year=2027,
        parental_leave_parent_salary=Decimal(4_800_000),
        household_income_for_childcare=Decimal(9_000_000),
    )
    events = expand_birth_event(birth_params, horizon_years=30)
    with_birth = run_projection(base_profile, base_assumptions, events)

    assert with_birth.total_net_worth_end < base.total_net_worth_end
    # 教育費総額 + 保育料 + 出産費用 - 児童手当 - 育休給付 の純支出が数百万〜
    diff = base.total_net_worth_end - with_birth.total_net_worth_end
    assert diff > Decimal(1_000_000)
    assert diff < Decimal(30_000_000)


def test_event_net_matches_events(base_profile, base_assumptions):
    """イベント差分の合計は events の総和と一致する(horizon 内の分)。"""
    birth_params = BirthEventParams(
        birth_year=2027,
        parental_leave_parent_salary=Decimal(4_800_000),
    )
    events = expand_birth_event(birth_params, horizon_years=25)
    # horizon 外(2026+25=2051以降)は無視されるのでテスト用に内側に収める
    result = run_projection(base_profile, base_assumptions, events)
    expected = sum(
        (d.amount for d in events if 2026 <= d.year <= 2055),
        Decimal(0),
    )
    assert result.total_event_net == expected


def test_zero_income_produces_zero_tax(base_assumptions):
    """収入 0 の世帯は所得税 0、社保 0。"""
    profile = HouseholdProfile(
        primary_salary=Decimal(0),
        spouse_salary=Decimal(0),
        base_annual_expense=Decimal(0),
    )
    result = run_projection(profile, base_assumptions)
    for row in result.rows:
        assert row.income_tax == 0
        assert row.social_insurance == 0
        # 住民税は均等割 6000 があるので > 0


def test_investment_return_grows_net_worth_faster(base_profile, base_assumptions):
    """投資リターン 0 と 5% で比較すると後者が純資産を上回る。"""
    zero_return = SimulationAssumptions(
        start_year=2026,
        horizon_years=30,
        investment_return_rate=Decimal(0),
    )
    high_return = SimulationAssumptions(
        start_year=2026,
        horizon_years=30,
        investment_return_rate=Decimal("0.05"),
    )
    r_zero = run_projection(base_profile, zero_return)
    r_high = run_projection(base_profile, high_return)
    assert r_high.total_net_worth_end > r_zero.total_net_worth_end


def test_take_home_is_positive_high_earner(base_profile, base_assumptions):
    """共働き世帯(900万)の手取りは毎年プラス。"""
    result = run_projection(base_profile, base_assumptions)
    for row in result.rows:
        assert row.take_home > 0


def test_to_dict_serialization(base_profile, base_assumptions):
    """API 化用 to_dict が Decimal を文字列化する。"""
    result = run_projection(base_profile, base_assumptions)
    d = result.to_dict()
    assert isinstance(d["rows"], list)
    assert isinstance(d["total_net_worth_end"], str)
    assert isinstance(d["rows"][0]["gross_income"], str)


def test_custom_horizon_years(base_profile):
    assumptions = SimulationAssumptions(start_year=2026, horizon_years=10)
    result = run_projection(base_profile, assumptions)
    assert len(result.rows) == 10
    assert result.rows[-1].year == 2035
