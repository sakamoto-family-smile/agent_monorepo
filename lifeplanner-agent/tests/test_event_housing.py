"""E02 住宅購入イベントのテスト。"""

from __future__ import annotations

from decimal import Decimal

import pytest
from agents.event_catalog import (
    EventCategory,
    HousingEventParams,
    expand_housing_event,
)
from agents.event_catalog.housing import (
    _annual_loan_payment,
    _remaining_balance_end_of_year,
)


@pytest.fixture
def base_params() -> HousingEventParams:
    return HousingEventParams(
        purchase_year=2028,
        price=Decimal(50_000_000),
        down_payment=Decimal(10_000_000),
        loan_term_years=35,
        interest_rate=Decimal("0.015"),
        property_type="condo",
        property_condition="new",
    )


# --- Loan arithmetic ---------------------------------------------------------


def test_annual_loan_payment_basic():
    """3000 万を 1.5% 35 年 元利均等 → 年額おおむね 110 万台。"""
    p = _annual_loan_payment(Decimal(30_000_000), Decimal("0.015"), 35)
    assert Decimal(1_000_000) < p < Decimal(1_300_000)


def test_annual_loan_payment_zero_interest():
    """金利 0 なら 単純に元本/年数。"""
    p = _annual_loan_payment(Decimal(35_000_000), Decimal(0), 35)
    assert p == Decimal(1_000_000)


def test_remaining_balance_decreases_over_time():
    """毎年の期末残債は単調減少し、最終年度末は 0 に近づく。"""
    prev = Decimal(30_000_000)
    for i in range(35):
        bal = _remaining_balance_end_of_year(
            Decimal(30_000_000), Decimal("0.015"), 35, i
        )
        assert bal <= prev + Decimal(1)  # 数値誤差許容
        prev = bal
    assert prev < Decimal(1000)  # 最終年度末はほぼ 0


# --- Event expansion ---------------------------------------------------------


def test_purchase_year_has_down_payment_and_closing_cost(base_params):
    deltas = expand_housing_event(base_params, horizon_years=30)
    one_times = [d for d in deltas if d.category == EventCategory.ONE_TIME]
    assert len(one_times) == 1
    # 頭金 1000万 + 諸費用 7% = 350万 → 1350 万の支出
    assert one_times[0].amount == Decimal(-13_500_000)
    assert one_times[0].year == 2028


def test_annual_loan_payment_runs_for_term_years(base_params):
    deltas = expand_housing_event(base_params, horizon_years=40)
    loan_payments = [d for d in deltas if d.label == "住宅ローン返済"]
    # loan_term_years=35 なので 35 年分
    assert len(loan_payments) == 35
    # 各年の返済額は同じ (元利均等 fixed)
    amounts = {d.amount for d in loan_payments}
    assert len(amounts) == 1


def test_loan_payment_truncates_at_horizon(base_params):
    """horizon が term より短い場合、horizon まで。"""
    deltas = expand_housing_event(base_params, horizon_years=10)
    loan_payments = [d for d in deltas if d.label == "住宅ローン返済"]
    assert len(loan_payments) == 10


def test_maintenance_runs_every_year(base_params):
    """維持費 (固都税 + 管理/修繕) は horizon 分。"""
    deltas = expand_housing_event(base_params, horizon_years=30)
    maint = [d for d in deltas if "維持費" in d.label]
    assert len(maint) == 30
    # 固都税 = 5000万 × 0.7% = 35 万、管理 30 万 → 年 65 万
    assert maint[0].amount == Decimal(-650_000)


def test_house_type_uses_house_maintenance_value():
    p = HousingEventParams(
        purchase_year=2028,
        price=Decimal(40_000_000),
        down_payment=Decimal(8_000_000),
        property_type="house",
        loan_term_years=30,
    )
    deltas = expand_housing_event(p, horizon_years=2)
    maint = [d for d in deltas if "維持費" in d.label]
    # 戸建: 修繕 15万 + 固都税 (4000万 × 0.7% = 28万) = 43万
    assert maint[0].amount == Decimal(-430_000)


def test_mortgage_credit_for_new_property_runs_13_years(base_params):
    deltas = expand_housing_event(base_params, horizon_years=30)
    credits = [d for d in deltas if d.label == "住宅ローン控除"]
    # 新築は 13 年
    assert len(credits) == 13
    # 全て正 (収入扱い)
    assert all(c.amount > 0 for c in credits)


def test_mortgage_credit_respects_general_balance_cap(base_params):
    """4000 万借入 > 2000 万キャップなので 初年控除 ≒ 2000 万 × 0.7% = 14 万。"""
    deltas = expand_housing_event(base_params, horizon_years=30)
    credits = sorted([d for d in deltas if d.label == "住宅ローン控除"], key=lambda d: d.year)
    # 初年度は借入残高が大きく、2000 万キャップで 14 万に丸まる
    assert Decimal(135_000) <= credits[0].amount <= Decimal(145_000)


def test_mortgage_credit_used_property_runs_10_years():
    p = HousingEventParams(
        purchase_year=2028,
        price=Decimal(30_000_000),
        down_payment=Decimal(5_000_000),
        property_condition="used",
        loan_term_years=25,
    )
    deltas = expand_housing_event(p, horizon_years=30)
    credits = [d for d in deltas if d.label == "住宅ローン控除"]
    assert len(credits) == 10


def test_disabling_mortgage_credit_removes_income():
    p = HousingEventParams(
        purchase_year=2028,
        price=Decimal(30_000_000),
        down_payment=Decimal(5_000_000),
        include_mortgage_credit=False,
    )
    deltas = expand_housing_event(p, horizon_years=30)
    assert not any(d.label == "住宅ローン控除" for d in deltas)


def test_energy_saving_raises_credit_cap():
    """省エネ住宅は借入残高キャップ 3000 万まで拡大 → 控除額も増える。"""
    general = HousingEventParams(
        purchase_year=2028,
        price=Decimal(60_000_000),
        down_payment=Decimal(10_000_000),
        energy_class="general",
    )
    eco = HousingEventParams(
        purchase_year=2028,
        price=Decimal(60_000_000),
        down_payment=Decimal(10_000_000),
        energy_class="energy_saving",
    )
    g_total = sum(
        (d.amount for d in expand_housing_event(general, horizon_years=15) if d.label == "住宅ローン控除"),
        Decimal(0),
    )
    e_total = sum(
        (d.amount for d in expand_housing_event(eco, horizon_years=15) if d.label == "住宅ローン控除"),
        Decimal(0),
    )
    assert e_total > g_total
