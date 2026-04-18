"""transaction リポジトリの UPSERT / 一覧動作を検証する。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from models.transaction import Transaction as DomainTransaction
from repositories.household import ensure_household
from repositories.transaction import list_transactions, upsert_transactions


def _tx(
    source_id: str,
    *,
    d: str = "2026-04-01",
    content: str = "x",
    amount: int = -1000,
    category: str = "食費",
    is_transfer: bool = False,
    is_target: bool = True,
) -> DomainTransaction:
    y, m, dd = d.split("-")
    return DomainTransaction(
        source_id=source_id,
        date=date(int(y), int(m), int(dd)),
        content=content,
        amount=Decimal(amount),
        account="銀行A",
        category=category,
        subcategory=None,
        memo=None,
        is_transfer=is_transfer,
        is_target=is_target,
    )


@pytest.mark.asyncio
async def test_upsert_inserts_new_rows(db_session):
    hh = "house-1"
    await ensure_household(db_session, hh)
    result = await upsert_transactions(db_session, hh, [_tx("a"), _tx("b")])
    assert result.inserted == 2
    assert result.updated == 0
    assert result.unchanged == 0
    await db_session.commit()


@pytest.mark.asyncio
async def test_upsert_is_idempotent(db_session):
    hh = "house-2"
    await ensure_household(db_session, hh)
    data = [_tx("a"), _tx("b")]

    first = await upsert_transactions(db_session, hh, data)
    await db_session.commit()

    second = await upsert_transactions(db_session, hh, data)
    await db_session.commit()

    assert first.inserted == 2
    assert second.inserted == 0
    assert second.unchanged == 2


@pytest.mark.asyncio
async def test_upsert_detects_field_changes(db_session):
    hh = "house-3"
    await ensure_household(db_session, hh)

    await upsert_transactions(db_session, hh, [_tx("a", amount=-1000)])
    await db_session.commit()

    result = await upsert_transactions(
        db_session, hh, [_tx("a", amount=-1500)]  # 金額変更
    )
    await db_session.commit()

    assert result.inserted == 0
    assert result.updated == 1
    assert result.unchanged == 0


@pytest.mark.asyncio
async def test_upsert_isolates_by_household(db_session):
    """同じ source_id でも household が違えば別レコード。"""
    await ensure_household(db_session, "h1")
    await ensure_household(db_session, "h2")

    r1 = await upsert_transactions(db_session, "h1", [_tx("same-id")])
    r2 = await upsert_transactions(db_session, "h2", [_tx("same-id")])
    await db_session.commit()

    assert r1.inserted == 1
    assert r2.inserted == 1


@pytest.mark.asyncio
async def test_upsert_empty_list(db_session):
    result = await upsert_transactions(db_session, "h-empty", [])
    assert result.inserted == 0
    assert result.total == 0


@pytest.mark.asyncio
async def test_list_excludes_transfers_by_default(db_session):
    hh = "h-list"
    await ensure_household(db_session, hh)
    await upsert_transactions(
        db_session, hh,
        [
            _tx("normal"),
            _tx("transfer", is_transfer=True),
            _tx("excluded", is_target=False),
        ],
    )
    await db_session.commit()

    rows, total = await list_transactions(db_session, hh)
    assert total == 1
    assert rows[0].source_id == "normal"


@pytest.mark.asyncio
async def test_list_pagination(db_session):
    hh = "h-page"
    await ensure_household(db_session, hh)
    await upsert_transactions(
        db_session, hh,
        [_tx(f"t{i}", d=f"2026-04-{i+1:02d}") for i in range(10)],
    )
    await db_session.commit()

    rows1, total = await list_transactions(db_session, hh, limit=4, offset=0)
    rows2, _ = await list_transactions(db_session, hh, limit=4, offset=4)

    assert total == 10
    assert len(rows1) == 4
    assert len(rows2) == 4
    # 重複なし
    ids1 = {r.source_id for r in rows1}
    ids2 = {r.source_id for r in rows2}
    assert not (ids1 & ids2)


@pytest.mark.asyncio
async def test_list_date_range(db_session):
    hh = "h-date"
    await ensure_household(db_session, hh)
    await upsert_transactions(
        db_session, hh,
        [
            _tx("a", d="2026-03-15"),
            _tx("b", d="2026-04-10"),
            _tx("c", d="2026-05-05"),
        ],
    )
    await db_session.commit()

    rows, total = await list_transactions(
        db_session, hh,
        start=date(2026, 4, 1), end=date(2026, 4, 30),
    )
    assert total == 1
    assert rows[0].source_id == "b"
