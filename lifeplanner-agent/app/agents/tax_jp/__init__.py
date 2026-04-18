"""日本税制計算モジュール (年版管理)。

- `loader.load_tax_table(year)` で YAML テーブルをロード
- `income_tax.calc_income_tax(...)` で所得税(+復興特別)
- `resident_tax.calc_resident_tax(...)` で住民税
- `social_insurance.calc_social_insurance(...)` で社保料(給与所得者)

設計方針:
  - LLM で税計算させず Python で純粋関数化(再現性・監査性のため)
  - 全て Decimal で計算。float 禁止
"""

from __future__ import annotations

from agents.tax_jp.income_tax import calc_income_tax, calc_salary_income_deduction
from agents.tax_jp.loader import TaxTable, load_tax_table
from agents.tax_jp.resident_tax import calc_resident_tax
from agents.tax_jp.social_insurance import SocialInsuranceResult, calc_social_insurance

__all__ = [
    "SocialInsuranceResult",
    "TaxTable",
    "calc_income_tax",
    "calc_resident_tax",
    "calc_salary_income_deduction",
    "calc_social_insurance",
    "load_tax_table",
]
