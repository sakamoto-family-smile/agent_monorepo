"""決定論的な長期プロジェクション。

- 年次キャッシュフロー (給与・社保・税・生活費・イベント差分)
- 純資産推移 (前年末 + 年次ネット)
- 投資リターンは定率で加味

Phase 2 スコープ:
  - 世帯は単一稼得者 + 複数イベントリスト入力
  - Monte Carlo は未実装 (Phase 4)
  - 退職後の年金収入は未実装 (Phase 4)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from agents.event_catalog.types import CashFlowDelta
from agents.tax_jp import (
    TaxTable,
    calc_income_tax,
    calc_resident_tax,
    calc_social_insurance,
    load_tax_table,
)

_ZERO = Decimal(0)


@dataclass(frozen=True)
class HouseholdProfile:
    """世帯の基本情報。simulator 入力。"""

    # 世帯主の現在の給与年収 (税引前)
    primary_salary: Decimal
    # 配偶者の給与年収 (0 なら単身世帯扱い)
    spouse_salary: Decimal = _ZERO
    # 年間の基本生活費 (食住光熱医療通信等、手取から差し引く)
    base_annual_expense: Decimal = Decimal(3_600_000)
    # 現在の流動資産合計 (預金 + 投資、プロジェクション開始時点)
    initial_net_worth: Decimal = _ZERO


@dataclass(frozen=True)
class SimulationAssumptions:
    """プロジェクション前提。年度切替可能な想定パラメータ。"""

    start_year: int
    horizon_years: int = 30
    # 給与上昇率 (年率)
    salary_growth_rate: Decimal = Decimal("0.01")
    # インフレ率 (生活費成長率)
    inflation_rate: Decimal = Decimal("0.01")
    # 投資リターン (流動資産への年率、手取-生活費-イベント の残余に適用)
    investment_return_rate: Decimal = Decimal("0.02")
    # 税制テーブル年 (None なら start_year を使用)
    tax_year: int | None = None


@dataclass(frozen=True)
class YearRow:
    """1 年分のプロジェクション結果。"""

    year: int
    gross_income: Decimal
    social_insurance: Decimal
    income_tax: Decimal
    resident_tax: Decimal
    take_home: Decimal
    living_expense: Decimal
    event_net: Decimal  # イベント差分 (収入 - 支出)
    annual_net: Decimal  # 年次ネット(take_home - living_expense + event_net)
    investment_gain: Decimal
    net_worth_end: Decimal  # 年末純資産


@dataclass(frozen=True)
class SimulationResult:
    """プロジェクション全体の結果。"""

    rows: list[YearRow]
    total_net_worth_end: Decimal  # 最終年末純資産
    total_take_home: Decimal
    total_tax_paid: Decimal
    total_social_insurance: Decimal
    total_event_net: Decimal

    def to_dict(self) -> dict:
        """API / JSON 化用。Decimal を str に寄せる。"""
        return {
            "rows": [
                {k: str(v) if isinstance(v, Decimal) else v for k, v in row.__dict__.items()}
                for row in self.rows
            ],
            "total_net_worth_end": str(self.total_net_worth_end),
            "total_take_home": str(self.total_take_home),
            "total_tax_paid": str(self.total_tax_paid),
            "total_social_insurance": str(self.total_social_insurance),
            "total_event_net": str(self.total_event_net),
        }


def _apply_rate(base: Decimal, rate: Decimal, years: int) -> Decimal:
    """複利で years 年後の値。"""
    if years <= 0:
        return base
    # (1 + rate) ** years を Decimal で計算
    result = base
    multiplier = Decimal(1) + rate
    for _ in range(years):
        result = result * multiplier
    return result


def _events_by_year(deltas: list[CashFlowDelta]) -> dict[int, Decimal]:
    """CashFlowDelta を年度キーの合計に畳む。"""
    acc: dict[int, Decimal] = {}
    for d in deltas:
        acc[d.year] = acc.get(d.year, _ZERO) + d.amount
    return acc


def _calc_household_taxes(
    household_salary: Decimal,
    table: TaxTable,
) -> tuple[Decimal, Decimal, Decimal]:
    """世帯給与から (社保, 所得税, 住民税) を返す。
    配偶者控除等の世帯特有ロジックは未実装(単一申告者で合算した近似)。
    """
    if household_salary <= 0:
        return _ZERO, _ZERO, _ZERO
    si = calc_social_insurance(household_salary, table=table)
    inc = calc_income_tax(
        household_salary,
        table=table,
        social_insurance_deduction=si.total,
    )
    res = calc_resident_tax(
        household_salary,
        table=table,
        social_insurance_deduction=si.total,
    )
    return si.total, inc, res


def run_projection(
    profile: HouseholdProfile,
    assumptions: SimulationAssumptions,
    events: list[CashFlowDelta] | None = None,
) -> SimulationResult:
    """30 年(既定)の決定論プロジェクションを実行する。

    年次フロー:
      1. 給与 = 基本給与 × (1 + growth) ** year_index  (世帯主+配偶者)
      2. 社保・所得税・住民税を世帯合算給与から計算
      3. 手取り = 給与 - 社保 - 所得税 - 住民税
      4. 生活費 = 基本生活費 × (1 + inflation) ** year_index
      5. イベント差分 = events の該当年度合算
      6. 年次ネット = 手取り - 生活費 + イベント差分
      7. 投資利益 = 前年末純資産 × investment_return_rate
      8. 年末純資産 = 前年末純資産 + 投資利益 + 年次ネット
    """
    events = events or []
    events_map = _events_by_year(events)

    tax_year = assumptions.tax_year or assumptions.start_year
    table = load_tax_table(tax_year)

    rows: list[YearRow] = []
    net_worth = profile.initial_net_worth
    total_take_home = _ZERO
    total_tax = _ZERO
    total_si = _ZERO
    total_event = _ZERO

    for i in range(assumptions.horizon_years):
        year = assumptions.start_year + i
        # 1. 給与 (複利で伸長)
        primary = _apply_rate(profile.primary_salary, assumptions.salary_growth_rate, i)
        spouse = _apply_rate(profile.spouse_salary, assumptions.salary_growth_rate, i)
        gross = primary + spouse

        # 2. 税金・社保 (世帯合算給与で近似)
        si_total, inc_tax, res_tax = _calc_household_taxes(gross, table)

        # 3. 手取り
        take_home = gross - si_total - inc_tax - res_tax

        # 4. 生活費
        living = _apply_rate(profile.base_annual_expense, assumptions.inflation_rate, i)

        # 5. イベント差分
        event_net = events_map.get(year, _ZERO)

        # 6. 年次ネット
        annual_net = take_home - living + event_net

        # 7. 投資利益 (前年末純資産ベース)
        investment_gain = net_worth * assumptions.investment_return_rate

        # 8. 年末純資産
        net_worth = net_worth + investment_gain + annual_net

        rows.append(
            YearRow(
                year=year,
                gross_income=gross,
                social_insurance=si_total,
                income_tax=inc_tax,
                resident_tax=res_tax,
                take_home=take_home,
                living_expense=living,
                event_net=event_net,
                annual_net=annual_net,
                investment_gain=investment_gain,
                net_worth_end=net_worth,
            )
        )

        total_take_home += take_home
        total_tax += inc_tax + res_tax
        total_si += si_total
        total_event += event_net

    return SimulationResult(
        rows=rows,
        total_net_worth_end=net_worth,
        total_take_home=total_take_home,
        total_tax_paid=total_tax,
        total_social_insurance=total_si,
        total_event_net=total_event,
    )
