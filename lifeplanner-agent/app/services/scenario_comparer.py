"""複数シナリオの決定論比較。

- ベースシナリオと 1+ の比較対象を受け取り、年次 KPI の差分を返す
- LLM は使わない (後段の Advisor で要約)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from agents.simulator import SimulationResult


@dataclass(frozen=True)
class ScenarioSummary:
    """単一シナリオの集計値。"""

    scenario_id: int
    name: str
    horizon_years: int
    total_net_worth_end: Decimal
    total_take_home: Decimal
    total_tax_paid: Decimal
    total_social_insurance: Decimal
    total_event_net: Decimal
    min_net_worth: Decimal
    min_net_worth_year: int
    max_net_worth: Decimal
    max_net_worth_year: int


@dataclass(frozen=True)
class ScenarioDiff:
    """比較対象とベースの差分。"""

    scenario_id: int
    name: str
    net_worth_diff: Decimal   # compare - base
    event_net_diff: Decimal
    take_home_diff: Decimal
    tax_diff: Decimal


@dataclass(frozen=True)
class ComparisonReport:
    base: ScenarioSummary
    compares: list[ScenarioSummary]
    diffs: list[ScenarioDiff]


def _summarize(scenario_id: int, name: str, result: SimulationResult) -> ScenarioSummary:
    if not result.rows:
        return ScenarioSummary(
            scenario_id=scenario_id,
            name=name,
            horizon_years=0,
            total_net_worth_end=Decimal(0),
            total_take_home=Decimal(0),
            total_tax_paid=Decimal(0),
            total_social_insurance=Decimal(0),
            total_event_net=Decimal(0),
            min_net_worth=Decimal(0),
            min_net_worth_year=0,
            max_net_worth=Decimal(0),
            max_net_worth_year=0,
        )
    # 純資産レンジ (年末値から)
    min_row = min(result.rows, key=lambda r: r.net_worth_end)
    max_row = max(result.rows, key=lambda r: r.net_worth_end)
    return ScenarioSummary(
        scenario_id=scenario_id,
        name=name,
        horizon_years=len(result.rows),
        total_net_worth_end=result.total_net_worth_end,
        total_take_home=result.total_take_home,
        total_tax_paid=result.total_tax_paid,
        total_social_insurance=result.total_social_insurance,
        total_event_net=result.total_event_net,
        min_net_worth=min_row.net_worth_end,
        min_net_worth_year=min_row.year,
        max_net_worth=max_row.net_worth_end,
        max_net_worth_year=max_row.year,
    )


def compare_scenarios(
    *,
    base: tuple[int, str, SimulationResult],
    compares: list[tuple[int, str, SimulationResult]],
) -> ComparisonReport:
    """ベース (id, name, result) と比較対象リストから ComparisonReport を作る。"""
    base_summary = _summarize(*base)
    compare_summaries = [_summarize(*c) for c in compares]
    diffs = [
        ScenarioDiff(
            scenario_id=cs.scenario_id,
            name=cs.name,
            net_worth_diff=cs.total_net_worth_end - base_summary.total_net_worth_end,
            event_net_diff=cs.total_event_net - base_summary.total_event_net,
            take_home_diff=cs.total_take_home - base_summary.total_take_home,
            tax_diff=cs.total_tax_paid - base_summary.total_tax_paid,
        )
        for cs in compare_summaries
    ]
    return ComparisonReport(base=base_summary, compares=compare_summaries, diffs=diffs)
