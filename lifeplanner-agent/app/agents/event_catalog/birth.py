"""E01: 出産・育児イベント展開。

5 項目を CashFlowDelta のリストへ展開:
  1. 出産一時費用 (出産育児一時金 50 万控除後)
  2. 育休給付 (雇用保険、上限 12 ヶ月)
  3. 児童手当 (0-18 歳、所得制限なし)
  4. 保育料 (0-2 歳、年収別ブラケット。3 歳以降は幼保無償化)
  5. 教育費 (幼稚園〜大学、公立/私立選択可)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from agents.event_catalog.benchmarks import (
    EducationBenchmark,
    load_education_benchmark,
)
from agents.event_catalog.types import CashFlowDelta, EventCategory

# 出産育児一時金 (2023 年 4 月〜)
_BIRTH_LUMP_SUM = Decimal(500_000)

# 教育段階ごとの年齢範囲と月数
_PRESCHOOL_AGES = (3, 4, 5)
_ELEMENTARY_AGES = tuple(range(6, 12))      # 6-11
_JUNIOR_HIGH_AGES = (12, 13, 14)
_HIGH_SCHOOL_AGES = (15, 16, 17)
_UNIVERSITY_AGES = (18, 19, 20, 21)
_CHILDCARE_AGES = (0, 1, 2)
_CHILD_ALLOWANCE_END_AGE = 18


@dataclass(frozen=True)
class BirthEventParams:
    """出産イベントのパラメータ。"""

    birth_year: int
    # 子の属性
    is_third_or_later: bool = False
    # 教育進路 (全段階で public/private または specific)
    elementary_private: bool = False
    junior_high_private: bool = False
    high_school_private: bool = False
    # 大学: "national_public" / "private_humanities" / "private_science" / None (進学しない)
    university_track: str | None = "national_public"
    # 保育園利用 (0-2 歳で認可保育所等)
    use_childcare: bool = True
    # 親の育休設定
    parental_leave_parent_salary: Decimal = Decimal(0)  # 育休取得者の年収
    parental_leave_months: int | None = None            # None なら benchmark 既定
    # 親の年収(保育料算定用、世帯合算)
    household_income_for_childcare: Decimal = Decimal(5_000_000)


def _pick_childcare_fee(income: Decimal, bench: EducationBenchmark) -> Decimal:
    """世帯年収から保育料月額を決定。"""
    for bracket in bench.childcare_brackets:
        if bracket.income_upto is None or income <= bracket.income_upto:
            return bracket.fee
    return bench.childcare_brackets[-1].fee


def _annual_child_allowance(age: int, params: BirthEventParams, bench: EducationBenchmark) -> Decimal:
    """児童手当の年額。2024 年拡充により所得制限なし・高校卒業まで。"""
    if age > _CHILD_ALLOWANCE_END_AGE:
        return Decimal(0)
    if params.is_third_or_later:
        monthly = bench.child_allowance_third_or_later
    elif age < 3:
        monthly = bench.child_allowance_under_3
    else:
        monthly = bench.child_allowance_over_3
    return monthly * 12


def _parental_leave_total(params: BirthEventParams, bench: EducationBenchmark) -> Decimal:
    """育休給付総額(全期間合計)。簡略化して birth_year にまとめて計上。"""
    salary = params.parental_leave_parent_salary
    if salary <= 0:
        return Decimal(0)
    duration = params.parental_leave_months or bench.parental_leave_default_duration_months
    if duration <= 0:
        return Decimal(0)
    monthly_salary = salary / Decimal(12)
    first_period_months = min(duration, 6)  # 180 日 = 約 6 ヶ月
    rest_months = max(duration - 6, 0)
    return (
        monthly_salary * bench.parental_leave_first_180d_rate * first_period_months
        + monthly_salary * bench.parental_leave_after_180d_rate * rest_months
    )


def _education_yearly_cost(age: int, params: BirthEventParams, bench: EducationBenchmark) -> Decimal:
    """子の年齢に対応する教育費年額。"""
    if age in _PRESCHOOL_AGES:
        # 幼保無償化により 3-5 歳は 0
        return Decimal(0)
    if age in _ELEMENTARY_AGES:
        return bench.elementary_private if params.elementary_private else bench.elementary_public
    if age in _JUNIOR_HIGH_AGES:
        return bench.junior_high_private if params.junior_high_private else bench.junior_high_public
    if age in _HIGH_SCHOOL_AGES:
        return bench.high_school_private if params.high_school_private else bench.high_school_public
    if age in _UNIVERSITY_AGES and params.university_track is not None:
        mapping = {
            "national_public": bench.university_national_public,
            "private_humanities": bench.university_private_humanities,
            "private_science": bench.university_private_science,
        }
        return mapping.get(params.university_track, Decimal(0))
    return Decimal(0)


def expand_birth_event(
    params: BirthEventParams,
    *,
    horizon_years: int = 30,
    benchmark: EducationBenchmark | None = None,
) -> list[CashFlowDelta]:
    """出産イベントを horizon_years 年分の CashFlowDelta に展開する。

    horizon_years: シミュ年数。birth_year から +horizon_years-1 年まで
    """
    bench = benchmark or load_education_benchmark()
    deltas: list[CashFlowDelta] = []

    # (1) 出産一時費用: 出産一時金 50 万を差し引いた純額
    birth_net_cost = bench.birth_one_time_cost - _BIRTH_LUMP_SUM
    deltas.append(
        CashFlowDelta(
            year=params.birth_year,
            amount=-birth_net_cost,
            category=EventCategory.ONE_TIME,
            label="出産一時費用 (一時金控除後)",
        )
    )

    # (2) 育休給付
    leave_total = _parental_leave_total(params, bench)
    if leave_total > 0:
        deltas.append(
            CashFlowDelta(
                year=params.birth_year,
                amount=leave_total,
                category=EventCategory.INCOME,
                label="育児休業給付金",
            )
        )

    # (3)-(5) 年齢ごとの展開
    for age in range(0, horizon_years):
        year = params.birth_year + age

        # (3) 児童手当
        allowance = _annual_child_allowance(age, params, bench)
        if allowance > 0:
            deltas.append(
                CashFlowDelta(
                    year=year,
                    amount=allowance,
                    category=EventCategory.CHILD_BENEFIT,
                    label=f"児童手当 (age {age})",
                )
            )

        # (4) 保育料 (0-2 歳で利用時のみ、3 歳以降は幼保無償化)
        if params.use_childcare and age in _CHILDCARE_AGES:
            monthly = _pick_childcare_fee(params.household_income_for_childcare, bench)
            annual = monthly * 12
            if annual > 0:
                deltas.append(
                    CashFlowDelta(
                        year=year,
                        amount=-annual,
                        category=EventCategory.RECURRING,
                        label=f"認可保育料 (age {age})",
                    )
                )

        # (5) 教育費
        edu = _education_yearly_cost(age, params, bench)
        if edu > 0:
            deltas.append(
                CashFlowDelta(
                    year=year,
                    amount=-edu,
                    category=EventCategory.RECURRING,
                    label=f"教育費 (age {age})",
                )
            )

    return deltas
