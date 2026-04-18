"""住民税(所得割 + 均等割)の計算。

前年所得に課税される仕組みだが、本シミュでは簡略化して当年所得に課税するモデル。
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from agents.tax_jp.income_tax import calc_salary_income_deduction
from agents.tax_jp.loader import TaxTable

_YEN = Decimal("1")


def _floor_yen(v: Decimal) -> Decimal:
    return v.quantize(_YEN, rounding=ROUND_DOWN)


def calc_resident_taxable_income(
    salary_income: Decimal,
    *,
    table: TaxTable,
    social_insurance_deduction: Decimal = Decimal(0),
    other_deductions: Decimal = Decimal(0),
) -> Decimal:
    """住民税の課税所得 = 給与収入 - 給与所得控除 - 社保控除 - 住民税基礎控除 - 他控除。"""
    salary_deduction = calc_salary_income_deduction(salary_income, table)
    employment_income = salary_income - salary_deduction
    taxable = (
        employment_income
        - social_insurance_deduction
        - table.basic_deduction_resident
        - other_deductions
    )
    return max(taxable, Decimal(0))


def calc_resident_tax(
    salary_income: Decimal,
    *,
    table: TaxTable,
    social_insurance_deduction: Decimal = Decimal(0),
    other_deductions: Decimal = Decimal(0),
    tax_credits: Decimal = Decimal(0),
) -> Decimal:
    """住民税年額(所得割 + 均等割 - 調整控除 - 税額控除)を返す。"""
    taxable = calc_resident_taxable_income(
        salary_income,
        table=table,
        social_insurance_deduction=social_insurance_deduction,
        other_deductions=other_deductions,
    )
    income_levy = _floor_yen(taxable * table.resident_income_rate)
    # 調整控除を差し引く(課税所得がある場合のみ)
    if taxable > 0:
        income_levy = max(income_levy - table.resident_adjustment_deduction, Decimal(0))
    # 税額控除(住宅ローン等)
    income_levy = max(income_levy - tax_credits, Decimal(0))
    # 均等割は課税所得 0 でも非課税限度を超えれば課される(簡略化して常に加算)
    return income_levy + table.resident_flat_amount
