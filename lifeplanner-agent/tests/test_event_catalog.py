"""EventCatalog / E01 出産イベントのテスト。"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

import pytest

from agents.event_catalog import (
    BirthEventParams,
    CashFlowDelta,
    EventCategory,
    expand_birth_event,
)


@pytest.fixture
def base_params() -> BirthEventParams:
    return BirthEventParams(
        birth_year=2026,
        parental_leave_parent_salary=Decimal(4_800_000),
        parental_leave_months=12,
        household_income_for_childcare=Decimal(7_000_000),
    )


def _sum_by_category(deltas: list[CashFlowDelta]) -> dict[EventCategory, Decimal]:
    totals: dict[EventCategory, Decimal] = defaultdict(lambda: Decimal(0))
    for d in deltas:
        totals[d.category] += d.amount
    return dict(totals)


def test_birth_cost_is_net_after_lump_sum(base_params):
    """出産費用は一時金 50 万控除後 = 55 万 - 50 万 = 5 万の支出。"""
    deltas = expand_birth_event(base_params, horizon_years=1)
    one_times = [d for d in deltas if d.category == EventCategory.ONE_TIME]
    assert len(one_times) == 1
    assert one_times[0].amount == Decimal(-50_000)


def test_parental_leave_benefit_is_income(base_params):
    """育休給付は出産年に income として計上。"""
    deltas = expand_birth_event(base_params, horizon_years=1)
    leaves = [d for d in deltas if d.label.startswith("育児休業")]
    assert len(leaves) == 1
    assert leaves[0].amount > 0
    # 給与 480 万, 12 ヶ月 = 月額 40 万
    # 6 ヶ月 * 67% * 40 万 + 6 ヶ月 * 50% * 40 万 = 160.8 万 + 120 万 = 280.8 万
    assert Decimal(2_500_000) < leaves[0].amount < Decimal(3_000_000)


def test_no_parental_leave_when_salary_zero():
    params = BirthEventParams(birth_year=2026, parental_leave_parent_salary=Decimal(0))
    deltas = expand_birth_event(params, horizon_years=1)
    leaves = [d for d in deltas if d.label.startswith("育児休業")]
    assert leaves == []


def test_child_allowance_covers_0_to_18(base_params):
    """児童手当は 0-18 歳。19 歳以降は 0。"""
    deltas = expand_birth_event(base_params, horizon_years=22)
    allowances = [d for d in deltas if d.category == EventCategory.CHILD_BENEFIT]
    # 0-18 の 19 年分
    assert len(allowances) == 19
    # 19 歳分のデータはない
    max_age_year = max(a.year for a in allowances)
    assert max_age_year == 2026 + 18


def test_child_allowance_under_3_is_higher(base_params):
    """0-2 歳は 15,000/月 = 年 18 万、3 歳以降は 10,000/月 = 年 12 万。"""
    deltas = expand_birth_event(base_params, horizon_years=5)
    allowances_by_year = {d.year: d.amount for d in deltas if d.category == EventCategory.CHILD_BENEFIT}
    # 0, 1, 2 歳は 18 万
    assert allowances_by_year[2026] == Decimal(180_000)
    assert allowances_by_year[2027] == Decimal(180_000)
    assert allowances_by_year[2028] == Decimal(180_000)
    # 3 歳以降は 12 万
    assert allowances_by_year[2029] == Decimal(120_000)
    assert allowances_by_year[2030] == Decimal(120_000)


def test_child_allowance_third_child_gets_higher(base_params):
    params = BirthEventParams(
        birth_year=2026,
        is_third_or_later=True,
    )
    deltas = expand_birth_event(params, horizon_years=2)
    allowances = [d for d in deltas if d.category == EventCategory.CHILD_BENEFIT]
    # 第3子は 30,000/月 = 年 36 万
    for a in allowances:
        assert a.amount == Decimal(360_000)


def test_childcare_only_for_0_to_2(base_params):
    """保育料は 0-2 歳のみ (3 歳以降は幼保無償化)。"""
    deltas = expand_birth_event(base_params, horizon_years=6)
    childcare = [d for d in deltas if "保育料" in d.label]
    assert len(childcare) == 3
    ages = sorted(d.year - 2026 for d in childcare)
    assert ages == [0, 1, 2]


def test_childcare_fee_by_income_bracket():
    """世帯年収で保育料が決まる。低所得ほど安い。"""
    low = BirthEventParams(birth_year=2026, household_income_for_childcare=Decimal(2_000_000))
    high = BirthEventParams(birth_year=2026, household_income_for_childcare=Decimal(15_000_000))
    low_deltas = expand_birth_event(low, horizon_years=3)
    high_deltas = expand_birth_event(high, horizon_years=3)
    low_childcare = [d for d in low_deltas if "保育料" in d.label]
    high_childcare = [d for d in high_deltas if "保育料" in d.label]
    # 低所得は非課税枠 → 保育料 0 → 項目すら出ない
    assert low_childcare == []
    # 高所得は年 80,000*12 = 96 万
    assert all(d.amount == Decimal(-960_000) for d in high_childcare)


def test_preschool_3_to_5_is_free(base_params):
    """幼稚園段階 (3-5 歳) は幼保無償化で教育費 0。"""
    deltas = expand_birth_event(base_params, horizon_years=6)
    for d in deltas:
        if d.category == EventCategory.RECURRING and 2029 <= d.year <= 2031:
            # 3-5 歳で recurring 支出が出ないこと (保育料も無料)
            assert "教育費" not in d.label


def test_public_track_total_education_cost(base_params):
    """デフォルト (全公立 + 国公立大) の教育費合計は妥当レンジ。

    概算:
      小 35.2 万 * 6 = 211 万
      中 53.8 万 * 3 = 161 万
      高 51.2 万 * 3 = 154 万
      大 82 万 * 4 = 328 万
      計 ~854 万
    """
    deltas = expand_birth_event(base_params, horizon_years=22)
    education = [d for d in deltas if "教育費" in d.label]
    total = sum((d.amount for d in education), Decimal(0))
    assert Decimal(-9_500_000) < total < Decimal(-7_500_000)


def test_all_private_track_is_significantly_more_expensive():
    """全私立 + 私立理系大の場合、公立コースより数倍高い。"""
    public = BirthEventParams(
        birth_year=2026,
        elementary_private=False,
        junior_high_private=False,
        high_school_private=False,
        university_track="national_public",
    )
    private = BirthEventParams(
        birth_year=2026,
        elementary_private=True,
        junior_high_private=True,
        high_school_private=True,
        university_track="private_science",
    )
    public_total = sum(
        (d.amount for d in expand_birth_event(public, horizon_years=22) if "教育費" in d.label),
        Decimal(0),
    )
    private_total = sum(
        (d.amount for d in expand_birth_event(private, horizon_years=22) if "教育費" in d.label),
        Decimal(0),
    )
    # 私立コースは公立コースの 2 倍以上の支出(絶対値で比較)
    assert abs(private_total) > abs(public_total) * 2


def test_no_university_cost_when_track_none():
    params = BirthEventParams(birth_year=2026, university_track=None)
    deltas = expand_birth_event(params, horizon_years=22)
    # 18-21 歳に教育費が出ていないこと
    university_edu = [
        d for d in deltas
        if "教育費" in d.label and 2044 <= d.year <= 2047
    ]
    assert university_edu == []


def test_horizon_years_limits_output(base_params):
    """horizon_years を超える年度の CashFlowDelta は出ない。"""
    deltas = expand_birth_event(base_params, horizon_years=5)
    years = {d.year for d in deltas}
    assert max(years) == 2026 + 4  # horizon 5 → index 0..4
