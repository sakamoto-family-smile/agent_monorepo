"""E04 車購入・買替イベントのテスト。"""

from __future__ import annotations

from decimal import Decimal

import pytest
from agents.event_catalog import (
    EventCategory,
    VehicleEventParams,
    expand_vehicle_event,
)


@pytest.fixture
def base_params() -> VehicleEventParams:
    return VehicleEventParams(
        first_purchase_year=2026,
        vehicle_class="compact",
        price=Decimal(2_500_000),
        hold_years=8,
        repeat_replacement=True,
    )


def test_first_purchase_has_full_price_and_closing(base_params):
    deltas = expand_vehicle_event(base_params, horizon_years=8)
    first = [d for d in deltas if d.category == EventCategory.ONE_TIME][0]
    # 本体 250 万 + 諸費用 10% = 275 万
    assert first.amount == Decimal(-2_750_000)
    assert first.year == 2026


def test_annual_cost_runs_for_hold_years(base_params):
    deltas = expand_vehicle_event(base_params, horizon_years=8)
    recurring = [d for d in deltas if d.category == EventCategory.RECURRING]
    assert len(recurring) == 8
    # コンパクト年間: 8+3.05+5+10+4+18 = 48.05 万
    expected = Decimal(-(80_000 + 30_500 + 50_000 + 100_000 + 40_000 + 180_000))
    assert recurring[0].amount == expected


def test_replacement_cycle_creates_second_purchase(base_params):
    """hold_years=8 で 16 年シミュすると 2 回購入。2 回目は下取り反映で支出額が減る。"""
    deltas = expand_vehicle_event(base_params, horizon_years=16)
    purchases = sorted(
        [d for d in deltas if d.category == EventCategory.ONE_TIME], key=lambda d: d.year
    )
    assert len(purchases) == 2
    assert purchases[0].year == 2026
    assert purchases[1].year == 2034
    # 初回: 275 万支出、2回目: 275 万 - 下取り (250万×0.25=62.5万) = 212.5 万
    assert purchases[0].amount == Decimal(-2_750_000)
    assert purchases[1].amount == Decimal(-2_125_000)


def test_no_repeat_when_flag_false():
    p = VehicleEventParams(
        first_purchase_year=2026,
        vehicle_class="sedan",
        price=Decimal(4_000_000),
        hold_years=5,
        repeat_replacement=False,
    )
    deltas = expand_vehicle_event(p, horizon_years=30)
    purchases = [d for d in deltas if d.category == EventCategory.ONE_TIME]
    assert len(purchases) == 1


def test_kei_is_cheapest_annual_cost():
    """軽自動車はコンパクトやセダンよりコストが安い。"""
    kei = VehicleEventParams(
        first_purchase_year=2026, vehicle_class="kei", price=Decimal(1_500_000), hold_years=10
    )
    suv = VehicleEventParams(
        first_purchase_year=2026, vehicle_class="suv", price=Decimal(5_000_000), hold_years=10
    )
    kei_annual = [
        d for d in expand_vehicle_event(kei, horizon_years=1) if d.category == EventCategory.RECURRING
    ][0]
    suv_annual = [
        d for d in expand_vehicle_event(suv, horizon_years=1) if d.category == EventCategory.RECURRING
    ][0]
    assert kei_annual.amount > suv_annual.amount  # less negative = smaller expense


def test_unknown_class_raises():
    p = VehicleEventParams(
        first_purchase_year=2026,
        vehicle_class="motorbike",  # type: ignore[arg-type]
        price=Decimal(500_000),
    )
    with pytest.raises(ValueError):
        expand_vehicle_event(p, horizon_years=5)


def test_horizon_truncates_second_hold_period(base_params):
    """horizon=12 の場合、2回目購入後 4 年分の保有費のみ。"""
    deltas = expand_vehicle_event(base_params, horizon_years=12)
    recurring_after_2034 = [d for d in deltas if d.category == EventCategory.RECURRING and d.year >= 2034]
    assert len(recurring_after_2034) == 4  # 2034-2037


def test_resale_ratio_3year_holding():
    """hold_years=3 だと下取り比率 0.55。"""
    p = VehicleEventParams(
        first_purchase_year=2026,
        vehicle_class="compact",
        price=Decimal(2_000_000),
        hold_years=3,
    )
    deltas = expand_vehicle_event(p, horizon_years=6)
    purchases = sorted(
        [d for d in deltas if d.category == EventCategory.ONE_TIME], key=lambda d: d.year
    )
    # 2 回目: 200万 + 諸費用 20万 - 下取り 110万 = 110 万
    assert purchases[1].amount == Decimal(-1_100_000)
