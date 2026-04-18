"""E02: 住宅購入イベント展開。

4 項目を CashFlowDelta のリストへ展開:
  1. 購入年の頭金 + 諸費用 (ONE_TIME)
  2. 年次ローン返済 (RECURRING、元利均等返済を想定)
  3. 年次維持費: 固都税 + 管理費/修繕積立 (RECURRING)
  4. 住宅ローン控除 (INCOME 扱い、控除期間のみ)

前提:
  - 金利変動なし (全期間固定)
  - 住宅ローン控除は所得税+住民税から引かれる形だが、簡略化して正のキャッシュフローとして計上
  - 修繕費は property_type が "condo" なら管理費、"house" なら戸建修繕
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from agents.event_catalog.benchmarks import (
    HousingBenchmark,
    load_housing_benchmark,
)
from agents.event_catalog.types import CashFlowDelta, EventCategory

PropertyType = Literal["condo", "house"]
PropertyCondition = Literal["new", "used"]
EnergyClass = Literal["general", "energy_saving"]


@dataclass(frozen=True)
class HousingEventParams:
    """住宅購入イベントのパラメータ。"""

    purchase_year: int
    price: Decimal                               # 物件価格 (本体)
    down_payment: Decimal                        # 頭金
    loan_term_years: int | None = None           # None なら benchmark 既定
    interest_rate: Decimal | None = None         # None なら benchmark 既定
    property_type: PropertyType = "condo"
    property_condition: PropertyCondition = "new"
    energy_class: EnergyClass = "general"        # 一般 / 省エネ
    include_mortgage_credit: bool = True


def _annual_loan_payment(principal: Decimal, annual_rate: Decimal, years: int) -> Decimal:
    """元利均等返済の年間返済額。

    principal: 借入元本
    annual_rate: 年利 (例 0.015)
    years: 返済期間
    """
    if principal <= 0 or years <= 0:
        return Decimal(0)
    if annual_rate == 0:
        return principal / Decimal(years)
    # 年複利で近似 (月次計算の簡略化)
    factor = (Decimal(1) + annual_rate) ** years
    return principal * annual_rate * factor / (factor - Decimal(1))


def _remaining_balance_end_of_year(
    principal: Decimal, annual_rate: Decimal, years: int, year_index: int
) -> Decimal:
    """年次均等返済 y 年目末の残債。

    year_index: 0 ベース (0 なら初年度末時点)
    """
    if year_index >= years:
        return Decimal(0)
    if annual_rate == 0:
        annual_pay = principal / Decimal(years)
        return max(principal - annual_pay * Decimal(year_index + 1), Decimal(0))
    annual_pay = _annual_loan_payment(principal, annual_rate, years)
    # 期末残債 = 元本 * (1+r)^(t+1) - 年返済 * ((1+r)^(t+1) - 1) / r
    t1 = Decimal(year_index + 1)
    f = (Decimal(1) + annual_rate) ** int(t1)
    balance = principal * f - annual_pay * (f - Decimal(1)) / annual_rate
    return max(balance, Decimal(0))


def expand_housing_event(
    params: HousingEventParams,
    *,
    horizon_years: int = 30,
    benchmark: HousingBenchmark | None = None,
) -> list[CashFlowDelta]:
    """住宅購入イベントを horizon_years 年分の CashFlowDelta に展開。"""
    bench = benchmark or load_housing_benchmark()
    deltas: list[CashFlowDelta] = []

    price = params.price
    down_payment = min(params.down_payment, price)
    principal = price - down_payment
    term_years = params.loan_term_years or bench.default_term_years
    interest_rate = (
        params.interest_rate if params.interest_rate is not None else bench.default_interest_rate
    )

    # (1) 購入年: 頭金 + 諸費用
    closing = price * bench.closing_cost_ratio
    one_time = down_payment + closing
    deltas.append(
        CashFlowDelta(
            year=params.purchase_year,
            amount=-one_time,
            category=EventCategory.ONE_TIME,
            label=f"住宅購入 頭金+諸費用 ({params.property_condition})",
        )
    )

    # (2) 年次ローン返済 (term_years 年間、horizon 内)
    annual_payment = _annual_loan_payment(principal, interest_rate, term_years)
    for i in range(term_years):
        year = params.purchase_year + i
        if year - params.purchase_year >= horizon_years:
            break
        deltas.append(
            CashFlowDelta(
                year=year,
                amount=-annual_payment,
                category=EventCategory.RECURRING,
                label="住宅ローン返済",
            )
        )

    # (3) 維持費 (保有中ずっと、horizon いっぱい)
    maintenance = (
        bench.annual_maintenance_condo
        if params.property_type == "condo"
        else bench.annual_maintenance_house
    )
    property_tax_annual = price * bench.property_tax_rate
    for i in range(horizon_years):
        year = params.purchase_year + i
        deltas.append(
            CashFlowDelta(
                year=year,
                amount=-(maintenance + property_tax_annual),
                category=EventCategory.RECURRING,
                label="住宅維持費 (固都税+管理/修繕)",
            )
        )

    # (4) 住宅ローン控除
    if params.include_mortgage_credit and principal > 0:
        credit_years = (
            bench.mortgage_credit_new_years
            if params.property_condition == "new"
            else bench.mortgage_credit_used_years
        )
        max_balance = (
            bench.mortgage_credit_max_balance_energy_saving
            if params.energy_class == "energy_saving"
            else bench.mortgage_credit_max_balance_general
        )
        for i in range(credit_years):
            year = params.purchase_year + i
            if year - params.purchase_year >= horizon_years:
                break
            # 年末残高 (簡略化: 年初残高ではなく i 年末)
            eoy_balance = _remaining_balance_end_of_year(
                principal, interest_rate, term_years, i
            )
            eligible = min(eoy_balance, max_balance)
            credit = eligible * bench.mortgage_credit_rate
            if credit > 0:
                deltas.append(
                    CashFlowDelta(
                        year=year,
                        amount=credit,
                        category=EventCategory.INCOME,
                        label="住宅ローン控除",
                    )
                )

    return deltas
