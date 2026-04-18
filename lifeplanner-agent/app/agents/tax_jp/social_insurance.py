"""社会保険料(給与所得者・協会けんぽ全国平均)計算。

簡略化のため月収は年収/12 で近似し、健康保険と厚生年金の標準報酬月額上限を適用。
介護保険(40 歳以上)は本 Phase では未実装。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from agents.tax_jp.loader import TaxTable

_YEN = Decimal("1")
_MONTHS = Decimal(12)


def _floor_yen(v: Decimal) -> Decimal:
    return v.quantize(_YEN, rounding=ROUND_DOWN)


@dataclass(frozen=True)
class SocialInsuranceResult:
    """社保料の内訳と合計(本人負担分、年額)。"""

    health: Decimal
    pension: Decimal
    employment: Decimal

    @property
    def total(self) -> Decimal:
        return self.health + self.pension + self.employment


def calc_social_insurance(
    salary_income: Decimal,
    *,
    table: TaxTable,
) -> SocialInsuranceResult:
    """給与年収から社会保険料の本人負担(年額)を算出。

    健康保険: min(月収, 健保上限) × rate × 12
    厚生年金: min(月収, 年金上限) × rate × 12
    雇用保険: 年収 × rate (月額上限なし、賃金総額ベース)
    """
    if salary_income <= 0:
        return SocialInsuranceResult(Decimal(0), Decimal(0), Decimal(0))

    monthly = salary_income / _MONTHS

    health_monthly_base = min(monthly, table.health_monthly_cap)
    pension_monthly_base = min(monthly, table.pension_monthly_cap)

    health = _floor_yen(health_monthly_base * table.health_insurance_rate) * _MONTHS
    pension = _floor_yen(pension_monthly_base * table.pension_rate) * _MONTHS
    employment = _floor_yen(salary_income * table.employment_insurance_rate)

    return SocialInsuranceResult(
        health=health,
        pension=pension,
        employment=employment,
    )
