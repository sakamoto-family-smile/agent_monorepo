"""決定論的な長期プロジェクション。

- 年次キャッシュフロー (給与・社保・税・生活費・イベント差分)
- 純資産推移 (前年末 + 年次ネット)
- 投資リターンは定率で加味

Phase 2 スコープ:
  - 世帯は単一稼得者 + 複数イベントリスト入力
  - Monte Carlo は未実装 (Phase 4)
  - 退職後の年金収入は未実装 (Phase 4)

PR 1 で追加:
  - `expense_baseline_by_category` でカテゴリ別生活費を渡せる
  - `YearRow.expense_breakdown` でカテゴリ別年額を出力 (合計 = living_expense)
  - `YearRow.event_breakdown` でイベント明細 (label / event_type / amount) を出力
  - 既存の `base_annual_expense` 単一値も後方互換で受ける
    (= "other" カテゴリ 1 つに集約される)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from agents.event_catalog.types import CashFlowDelta, EventCategory
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
    # `expense_baseline_by_category` が指定されていればそちらを優先。
    base_annual_expense: Decimal = Decimal(3_600_000)
    # カテゴリ別生活費の年額 (canonical_category -> 円)。
    # PR 1 で追加: 取り込んだ transactions から生成されるベースライン。
    # None なら `base_annual_expense` を {"other": ...} の単一カテゴリ扱い。
    expense_baseline_by_category: dict[str, Decimal] | None = None
    # 現在の流動資産合計 (預金 + 投資、プロジェクション開始時点)
    initial_net_worth: Decimal = _ZERO

    def resolved_baseline(self) -> dict[str, Decimal]:
        """カテゴリ別 baseline を必ず dict で返す (None なら base_annual_expense を変換)。"""
        if self.expense_baseline_by_category:
            return dict(self.expense_baseline_by_category)
        return {"other": self.base_annual_expense}


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
class EventLine:
    """1 イベントが 1 年に発生させる差分の 1 行 (UI 表示用)。

    `YearRow.event_breakdown` に並ぶ。amount は CashFlowDelta と同符号
    (正=収入/給付、負=支出)。
    """

    event_type: str       # "E01" / "E02" / "E04" 等
    category: str         # EventCategory.value (income / one_time / recurring / child_benefit)
    label: str            # "出産一時費用" / "児童手当 (3歳)" / "住宅ローン" 等
    amount: Decimal


@dataclass(frozen=True)
class YearRow:
    """1 年分のプロジェクション結果。"""

    year: int
    gross_income: Decimal
    social_insurance: Decimal
    income_tax: Decimal
    resident_tax: Decimal
    take_home: Decimal
    living_expense: Decimal              # 合計 (= sum(expense_breakdown.values()))
    expense_breakdown: dict[str, Decimal] = field(default_factory=dict)
    event_net: Decimal = _ZERO           # イベント差分 (収入 - 支出)
    event_breakdown: list[EventLine] = field(default_factory=list)
    annual_net: Decimal = _ZERO          # 年次ネット (take_home - living_expense + event_net)
    investment_gain: Decimal = _ZERO
    net_worth_end: Decimal = _ZERO  # 年末純資産


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
        """API / JSON 化用。Decimal を str に寄せる。

        PR 1 で `expense_breakdown` (dict) と `event_breakdown` (list[EventLine])
        を平準化する。
        """
        return {
            "rows": [_year_row_to_dict(row) for row in self.rows],
            "total_net_worth_end": str(self.total_net_worth_end),
            "total_take_home": str(self.total_take_home),
            "total_tax_paid": str(self.total_tax_paid),
            "total_social_insurance": str(self.total_social_insurance),
            "total_event_net": str(self.total_event_net),
        }


def _year_row_to_dict(row: YearRow) -> dict:
    """YearRow → JSON 可能な dict (Decimal を str に変換)。"""
    return {
        "year": row.year,
        "gross_income": str(row.gross_income),
        "social_insurance": str(row.social_insurance),
        "income_tax": str(row.income_tax),
        "resident_tax": str(row.resident_tax),
        "take_home": str(row.take_home),
        "living_expense": str(row.living_expense),
        "expense_breakdown": {k: str(v) for k, v in row.expense_breakdown.items()},
        "event_net": str(row.event_net),
        "event_breakdown": [
            {
                "event_type": line.event_type,
                "category": line.category,
                "label": line.label,
                "amount": str(line.amount),
            }
            for line in row.event_breakdown
        ],
        "annual_net": str(row.annual_net),
        "investment_gain": str(row.investment_gain),
        "net_worth_end": str(row.net_worth_end),
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
    """CashFlowDelta を年度キーの合計に畳む (合計値のみ、明細は別関数)。"""
    acc: dict[int, Decimal] = {}
    for d in deltas:
        acc[d.year] = acc.get(d.year, _ZERO) + d.amount
    return acc


def _events_breakdown_by_year(deltas: list[CashFlowDelta]) -> dict[int, list[EventLine]]:
    """CashFlowDelta を年度キーの明細リストに畳む (UI 用)。

    catalog 関数は CashFlowDelta(event_type="") で生成し、scenario_runner が
    `dataclasses.replace` で event_type を設定する想定。空のままなら "?" を表示。
    """
    acc: dict[int, list[EventLine]] = {}
    for d in deltas:
        line = EventLine(
            event_type=d.event_type or "?",
            category=d.category.value
            if isinstance(d.category, EventCategory)
            else str(d.category),
            label=d.label,
            amount=d.amount,
        )
        acc.setdefault(d.year, []).append(line)
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
    events_breakdown_map = _events_breakdown_by_year(events)

    tax_year = assumptions.tax_year or assumptions.start_year
    table = load_tax_table(tax_year)

    baseline_by_category = profile.resolved_baseline()

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

        # 4. 生活費 (カテゴリ別に inflation 適用 → 合計)
        expense_breakdown = {
            cat: _apply_rate(amount, assumptions.inflation_rate, i)
            for cat, amount in baseline_by_category.items()
        }
        living = sum(expense_breakdown.values(), _ZERO)

        # 5. イベント差分 (合計 + 明細)
        event_net = events_map.get(year, _ZERO)
        event_lines = events_breakdown_map.get(year, [])

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
                expense_breakdown=expense_breakdown,
                event_net=event_net,
                event_breakdown=event_lines,
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
