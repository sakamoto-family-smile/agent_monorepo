"""PR 1: 取り込み済 transactions からカテゴリ別生活費 baseline を生成。"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from models.transaction import Transaction as DomainTransaction
from repositories.household import ensure_household
from repositories.transaction import upsert_transactions
from services.expense_baseline import (
    baseline_from_amounts,
    compute_expense_baseline,
    empty_baseline,
)


def _tx(
    source_id: str,
    *,
    d: date,
    amount: int,
    canonical: str,
    expense_type: str = "variable",
    is_transfer: bool = False,
    is_target: bool = True,
) -> DomainTransaction:
    return DomainTransaction(
        source_id=source_id,
        date=d,
        content="x",
        amount=Decimal(amount),
        account="銀行A",
        category="ダミー",
        subcategory=None,
        canonical_category=canonical,
        expense_type=expense_type,
        memo=None,
        is_transfer=is_transfer,
        is_target=is_target,
    )


@pytest.mark.asyncio
async def test_compute_baseline_sums_by_category(db_session):
    """直近 365 日に全部入る額なら、合計 = baseline.annual_amount。"""
    hh = "house-1"
    await ensure_household(db_session, hh)
    today = date(2026, 5, 1)
    txs = [
        _tx("food-1", d=today - timedelta(days=10), amount=-50_000, canonical="food"),
        _tx("food-2", d=today - timedelta(days=20), amount=-70_000, canonical="food"),
        _tx("housing-1", d=today - timedelta(days=30), amount=-100_000, canonical="housing", expense_type="fixed"),
    ]
    await upsert_transactions(db_session, hh, txs)
    await db_session.commit()

    baseline = await compute_expense_baseline(db_session, hh, end=today, lookback_days=365)
    assert "food" in baseline.by_category
    assert baseline.by_category["food"].annual_amount == Decimal(120_000)
    assert baseline.by_category["food"].expense_type == "variable"
    assert baseline.by_category["housing"].annual_amount == Decimal(100_000)
    assert baseline.by_category["housing"].expense_type == "fixed"


@pytest.mark.asyncio
async def test_compute_baseline_excludes_income(db_session):
    """expense_type='income' (給与等) は baseline から除外。"""
    hh = "house-2"
    await ensure_household(db_session, hh)
    today = date(2026, 5, 1)
    txs = [
        _tx("salary", d=today - timedelta(days=10), amount=300_000,
            canonical="salary", expense_type="income"),
        _tx("food", d=today - timedelta(days=10), amount=-50_000, canonical="food"),
    ]
    await upsert_transactions(db_session, hh, txs)
    await db_session.commit()

    baseline = await compute_expense_baseline(db_session, hh, end=today, lookback_days=365)
    assert "salary" not in baseline.by_category
    assert "food" in baseline.by_category


@pytest.mark.asyncio
async def test_compute_baseline_excludes_transfers_and_non_target(db_session):
    hh = "house-3"
    await ensure_household(db_session, hh)
    today = date(2026, 5, 1)
    txs = [
        _tx("transfer", d=today - timedelta(days=5), amount=-100_000,
            canonical="cash_transfer", is_transfer=True),
        _tx("non-target", d=today - timedelta(days=5), amount=-100_000,
            canonical="other", is_target=False),
        _tx("real", d=today - timedelta(days=5), amount=-50_000, canonical="food"),
    ]
    await upsert_transactions(db_session, hh, txs)
    await db_session.commit()

    baseline = await compute_expense_baseline(db_session, hh, end=today, lookback_days=365)
    # cash_transfer / non-target は除外、food のみ残る
    assert set(baseline.by_category.keys()) == {"food"}


@pytest.mark.asyncio
async def test_compute_baseline_annualizes_short_lookback(db_session):
    """6 ヶ月 (180 日) lookback で 60_000 円使った → 年率換算で約 60_000 * (365/180) ≒ 121,667。"""
    hh = "house-4"
    await ensure_household(db_session, hh)
    today = date(2026, 5, 1)
    txs = [
        _tx("food-1", d=today - timedelta(days=30), amount=-30_000, canonical="food"),
        _tx("food-2", d=today - timedelta(days=60), amount=-30_000, canonical="food"),
    ]
    await upsert_transactions(db_session, hh, txs)
    await db_session.commit()

    baseline = await compute_expense_baseline(db_session, hh, end=today, lookback_days=180)
    food_annual = baseline.by_category["food"].annual_amount
    # 60_000 * (365 / 180) ≒ 121_667
    assert Decimal(120_000) <= food_annual <= Decimal(125_000)


@pytest.mark.asyncio
async def test_compute_baseline_empty_when_no_transactions(db_session):
    hh = "house-5"
    await ensure_household(db_session, hh)
    baseline = await compute_expense_baseline(db_session, hh, end=date(2026, 5, 1))
    assert baseline.by_category == {}
    assert baseline.total_annual == Decimal(0)


def test_baseline_from_amounts_helper():
    b = baseline_from_amounts({
        "food": Decimal(600_000),
        "housing": Decimal(1_200_000),
        "ignore_zero": Decimal(0),  # 0 は捨てる
    })
    assert set(b.by_category.keys()) == {"food", "housing"}
    assert b.total_annual == Decimal(1_800_000)
    assert b.to_amounts_dict() == {
        "food": Decimal(600_000),
        "housing": Decimal(1_200_000),
    }


def test_empty_baseline_helper():
    b = empty_baseline()
    assert b.by_category == {}
    assert b.total_annual == Decimal(0)
