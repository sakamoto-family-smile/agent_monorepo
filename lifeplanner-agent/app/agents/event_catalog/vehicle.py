"""E04: 車購入・買替イベント展開。

項目:
  1. 購入年: 車両価格 + 諸費用 - 下取り (ONE_TIME)
  2. 年次保有コスト: 保険・自動車税・車検・燃料・整備・駐車場 (RECURRING)
  3. 買替周期が来たら (2) を新しい価格で繰り返す

前提:
  - 買替周期は default_hold_years (8 年)、params で上書き可能
  - 車両価格は買替のたびに買い替え前と同額 (インフレや値上がりは加味しない)
  - 下取り比率は保有年数から resale_ratio_by_years で決定 (最大年数を超えたら最小比率)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from agents.event_catalog.benchmarks import (
    VehicleBenchmark,
    load_vehicle_benchmark,
)
from agents.event_catalog.types import CashFlowDelta, EventCategory

VehicleClass = Literal["compact", "sedan", "suv", "kei", "ev"]


@dataclass(frozen=True)
class VehicleEventParams:
    """車購入・買替イベントのパラメータ。"""

    first_purchase_year: int
    vehicle_class: VehicleClass = "compact"
    price: Decimal = Decimal(2_500_000)
    # 買替時の下取り比率を反映するか (初回購入時は下取りなし)
    hold_years: int | None = None
    # 買替を繰り返すか (False なら初回購入のみ)
    repeat_replacement: bool = True


def _resale_ratio(hold_years: int, bench: VehicleBenchmark) -> Decimal:
    """保有年数に対応する下取り比率。ベンチマークの最も近い (以下の) 年数を採用。"""
    sorted_years = sorted(bench.resale_ratio_by_years.keys())
    ratio = Decimal(0)
    for y in sorted_years:
        if hold_years >= y:
            ratio = bench.resale_ratio_by_years[y]
    if hold_years < sorted_years[0]:
        ratio = bench.resale_ratio_by_years[sorted_years[0]]
    return ratio


def expand_vehicle_event(
    params: VehicleEventParams,
    *,
    horizon_years: int = 30,
    benchmark: VehicleBenchmark | None = None,
) -> list[CashFlowDelta]:
    """車購入・買替イベントを horizon_years 年分の CashFlowDelta に展開。"""
    bench = benchmark or load_vehicle_benchmark()
    deltas: list[CashFlowDelta] = []

    hold_years = params.hold_years or bench.default_hold_years
    annual_cost = bench.annual_by_class.get(params.vehicle_class)
    if annual_cost is None:
        raise ValueError(f"Unknown vehicle_class: {params.vehicle_class}")

    horizon_end_year = params.first_purchase_year + horizon_years - 1

    # 購入イベントを first_purchase_year を起点に hold_years 周期で繰り返す
    purchase_year = params.first_purchase_year
    is_first = True
    while purchase_year <= horizon_end_year:
        # (1) 購入: 車両価格 + 諸費用 (初回以外は下取り収入で相殺)
        closing = params.price * bench.closing_cost_ratio
        if is_first:
            one_time = params.price + closing
        else:
            resale = params.price * _resale_ratio(hold_years, bench)
            one_time = params.price + closing - resale
        deltas.append(
            CashFlowDelta(
                year=purchase_year,
                amount=-one_time,
                category=EventCategory.ONE_TIME,
                label=f"車両購入 ({params.vehicle_class})",
            )
        )

        # (2) 保有期間中の年次コスト
        for i in range(hold_years):
            y = purchase_year + i
            if y > horizon_end_year:
                break
            deltas.append(
                CashFlowDelta(
                    year=y,
                    amount=-annual_cost.total,
                    category=EventCategory.RECURRING,
                    label="車両保有費",
                )
            )

        if not params.repeat_replacement:
            break
        purchase_year += hold_years
        is_first = False

    return deltas
