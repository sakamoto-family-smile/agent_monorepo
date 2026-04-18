from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from models.transaction import Transaction as DomainTransaction
from repositories.household import ensure_household
from repositories.transaction import upsert_transactions
from services.category_mapper import load_category_mapper
from services.summary import compute_summary


def _tx(source_id: str, *, d: str, amount: int, category: str, is_transfer: bool = False) -> DomainTransaction:
    y, m, dd = d.split("-")
    canonical = load_category_mapper().resolve(category)
    return DomainTransaction(
        source_id=source_id,
        date=date(int(y), int(m), int(dd)),
        content="x",
        amount=Decimal(amount),
        account="銀行A",
        category=category,
        subcategory=None,
        canonical_category=canonical.canonical,
        expense_type=canonical.expense_type,
        memo=None,
        is_transfer=is_transfer,
        is_target=True,
    )


@pytest.mark.asyncio
async def test_compute_summary_totals(db_session):
    hh = "s-totals"
    await ensure_household(db_session, hh)
    await upsert_transactions(
        db_session, hh,
        [
            _tx("in1", d="2026-04-01", amount=300000, category="収入"),
            _tx("out1", d="2026-04-02", amount=-1200, category="食費"),
            _tx("out2", d="2026-04-03", amount=-8000, category="食費"),
            _tx("out3", d="2026-04-04", amount=-5000, category="交通費"),
            _tx("tr", d="2026-04-05", amount=-50000, category="振替", is_transfer=True),
        ],
    )
    await db_session.commit()

    s = await compute_summary(
        db_session, hh, start=date(2026, 4, 1), end=date(2026, 4, 30)
    )
    # 振替は除外、収支計算
    assert s.total_income == Decimal("300000")
    assert s.total_expense == Decimal("14200")  # 1200+8000+5000
    assert s.net == Decimal("285800")


@pytest.mark.asyncio
async def test_compute_summary_monthly_breakdown(db_session):
    hh = "s-monthly"
    await ensure_household(db_session, hh)
    await upsert_transactions(
        db_session, hh,
        [
            _tx("a", d="2026-03-15", amount=-1000, category="食費"),
            _tx("b", d="2026-04-10", amount=-2000, category="食費"),
            _tx("c", d="2026-04-20", amount=100000, category="収入"),
            _tx("d", d="2026-05-05", amount=-3000, category="食費"),
        ],
    )
    await db_session.commit()

    s = await compute_summary(
        db_session, hh, start=date(2026, 1, 1), end=date(2026, 12, 31)
    )
    months = {m.year_month: m for m in s.monthly}
    assert months["2026-03"].expense == Decimal("1000")
    assert months["2026-04"].income == Decimal("100000")
    assert months["2026-04"].expense == Decimal("2000")
    assert months["2026-05"].expense == Decimal("3000")


@pytest.mark.asyncio
async def test_compute_summary_categories_sorted(db_session):
    hh = "s-cats"
    await ensure_household(db_session, hh)
    await upsert_transactions(
        db_session, hh,
        [
            _tx("a", d="2026-04-01", amount=-1000, category="食費"),
            _tx("b", d="2026-04-02", amount=-2000, category="食費"),
            _tx("c", d="2026-04-03", amount=-10000, category="教養・教育"),
            _tx("d", d="2026-04-04", amount=-500, category="交通費"),
        ],
    )
    await db_session.commit()

    s = await compute_summary(
        db_session, hh, start=date(2026, 4, 1), end=date(2026, 4, 30)
    )
    # canonical 名で降順
    assert [c.category for c in s.categories] == ["education", "food", "transportation"]
    assert s.categories[0].expense == Decimal("10000")
    assert s.categories[1].count == 2


@pytest.mark.asyncio
async def test_compute_summary_empty_household(db_session):
    hh = "s-empty"
    await ensure_household(db_session, hh)
    await db_session.commit()

    s = await compute_summary(
        db_session, hh, start=date(2026, 4, 1), end=date(2026, 4, 30)
    )
    assert s.total_income == Decimal("0")
    assert s.total_expense == Decimal("0")
    assert s.monthly == []
    assert s.categories == []
    assert s.savings_rate == Decimal("0")
    assert s.expense_types.total == Decimal("0")


@pytest.mark.asyncio
async def test_compute_summary_expense_types(db_session):
    """固定費(住宅+通信) / 変動費(食費+交通費) の分解を検証。"""
    hh = "s-types"
    await ensure_household(db_session, hh)
    await upsert_transactions(
        db_session, hh,
        [
            # 収入
            _tx("in", d="2026-04-01", amount=500_000, category="給与"),
            # 固定費
            _tx("h1", d="2026-04-02", amount=-120_000, category="住宅"),
            _tx("c1", d="2026-04-03", amount=-8_000, category="通信費"),
            # 変動費
            _tx("f1", d="2026-04-10", amount=-40_000, category="食費"),
            _tx("t1", d="2026-04-15", amount=-5_000, category="交通費"),
        ],
    )
    await db_session.commit()

    s = await compute_summary(
        db_session, hh, start=date(2026, 4, 1), end=date(2026, 4, 30)
    )
    assert s.total_income == Decimal("500000")
    assert s.expense_types.fixed == Decimal("128000")   # 120k + 8k
    assert s.expense_types.variable == Decimal("45000")  # 40k + 5k
    # 貯蓄率 = (500k - 173k) / 500k = 327k / 500k = 0.654
    assert s.savings_rate == Decimal("327000") / Decimal("500000")


@pytest.mark.asyncio
async def test_savings_rate_is_zero_when_income_zero(db_session):
    """支出だけの月は savings_rate=0 (ZeroDivisionError を起こさない)。"""
    hh = "s-no-income"
    await ensure_household(db_session, hh)
    await upsert_transactions(
        db_session, hh,
        [_tx("x", d="2026-04-01", amount=-10_000, category="食費")],
    )
    await db_session.commit()
    s = await compute_summary(
        db_session, hh, start=date(2026, 4, 1), end=date(2026, 4, 30)
    )
    assert s.total_income == Decimal("0")
    assert s.savings_rate == Decimal("0")
