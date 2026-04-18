from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from models.transaction import Transaction as DomainTransaction
from repositories.household import ensure_household
from repositories.transaction import upsert_transactions
from services.summary import compute_summary


def _tx(source_id: str, *, d: str, amount: int, category: str, is_transfer: bool = False) -> DomainTransaction:
    y, m, dd = d.split("-")
    return DomainTransaction(
        source_id=source_id,
        date=date(int(y), int(m), int(dd)),
        content="x",
        amount=Decimal(amount),
        account="銀行A",
        category=category,
        subcategory=None,
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
            _tx("c", d="2026-04-03", amount=-10000, category="教育"),
            _tx("d", d="2026-04-04", amount=-500, category="交通費"),
        ],
    )
    await db_session.commit()

    s = await compute_summary(
        db_session, hh, start=date(2026, 4, 1), end=date(2026, 4, 30)
    )
    # 降順
    assert [c.category for c in s.categories] == ["教育", "食費", "交通費"]
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
