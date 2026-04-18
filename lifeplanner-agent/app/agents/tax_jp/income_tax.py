"""所得税(給与所得者向け、復興特別所得税含む)の計算。

入力は年額。Decimal で計算し、最終的に円単位で切り捨て。
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from agents.tax_jp.loader import TaxTable

_YEN = Decimal("1")


def _floor_yen(v: Decimal) -> Decimal:
    """円未満切り捨て。"""
    return v.quantize(_YEN, rounding=ROUND_DOWN)


def calc_salary_income_deduction(salary_income: Decimal, table: TaxTable) -> Decimal:
    """給与収入 -> 給与所得控除額。"""
    if salary_income <= 0:
        return Decimal(0)
    for bracket in table.salary_deduction_brackets:
        if bracket.upto is None or salary_income <= bracket.upto:
            if bracket.flat_deduction is not None:
                return bracket.flat_deduction
            # 給与収入 * rate + offset
            return _floor_yen(salary_income * bracket.rate + bracket.offset)
    # どのブラケットにも当てはまらない(= 上限超え)
    return table.salary_deduction_cap


def calc_taxable_income(
    salary_income: Decimal,
    *,
    table: TaxTable,
    social_insurance_deduction: Decimal = Decimal(0),
    other_deductions: Decimal = Decimal(0),
) -> Decimal:
    """所得税の課税所得 = 給与収入 - 給与所得控除 - 社保控除 - 基礎控除 - 他控除。"""
    salary_deduction = calc_salary_income_deduction(salary_income, table)
    employment_income = salary_income - salary_deduction
    taxable = (
        employment_income
        - social_insurance_deduction
        - table.basic_deduction_income
        - other_deductions
    )
    return max(taxable, Decimal(0))


def _apply_brackets(taxable: Decimal, table: TaxTable) -> Decimal:
    """累進税率 + 速算控除方式で税額を算出。"""
    if taxable <= 0:
        return Decimal(0)
    for bracket in table.income_tax_brackets:
        if bracket.upto is None or taxable <= bracket.upto:
            return _floor_yen(taxable * bracket.rate - bracket.deduction)
    # 到達しない想定(最終ブラケットは upto=None)
    return Decimal(0)


def calc_income_tax(
    salary_income: Decimal,
    *,
    table: TaxTable,
    social_insurance_deduction: Decimal = Decimal(0),
    other_deductions: Decimal = Decimal(0),
    tax_credits: Decimal = Decimal(0),
) -> Decimal:
    """所得税額(復興特別所得税込み)を返す。

    tax_credits: 住宅ローン控除等の税額控除(基準所得税額から直接差引)
    """
    taxable = calc_taxable_income(
        salary_income,
        table=table,
        social_insurance_deduction=social_insurance_deduction,
        other_deductions=other_deductions,
    )
    base = _apply_brackets(taxable, table)
    after_credit = max(base - tax_credits, Decimal(0))
    surtax = _floor_yen(after_credit * table.reconstruction_surtax_rate)
    return after_credit + surtax
