"""
取引の UPSERT と問い合わせ。

UPSERT は (household_id, source_id) のユニーク制約を利用。
SQLite/Postgres 両対応のため、明示的に「存在確認 → INSERT/UPDATE」で実装する
（Postgres の ON CONFLICT, SQLite の INSERT OR REPLACE を使い分けるのを避ける）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Transaction
from models.transaction import Transaction as DomainTransaction


@dataclass(frozen=True)
class UpsertResult:
    inserted: int
    updated: int
    unchanged: int

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.unchanged


def _domain_to_orm_kwargs(household_id: str, tx: DomainTransaction) -> dict:
    return {
        "household_id": household_id,
        "source_id": tx.source_id,
        "date": tx.date,
        "content": tx.content,
        "amount": tx.amount,
        "account": tx.account,
        "category": tx.category,
        "subcategory": tx.subcategory,
        "canonical_category": tx.canonical_category,
        "expense_type": tx.expense_type,
        "memo": tx.memo,
        "is_transfer": tx.is_transfer,
        "is_target": tx.is_target,
    }


def _fields_differ(existing: Transaction, data: dict) -> bool:
    for key in (
        "date", "content", "amount", "account",
        "category", "subcategory",
        "canonical_category", "expense_type",
        "memo",
        "is_transfer", "is_target",
    ):
        if getattr(existing, key) != data[key]:
            return True
    return False


async def upsert_transactions(
    session: AsyncSession,
    household_id: str,
    transactions: list[DomainTransaction],
) -> UpsertResult:
    """
    Transaction を (household_id, source_id) キーで UPSERT する。
    source_id が空のレコードは skip されずに毎回 INSERT される（望ましくないが、
    MF CSV は通常 ID 列を持つのでこのケースはまれ）。
    """
    if not transactions:
        return UpsertResult(0, 0, 0)

    # source_id リストで既存レコードを一括取得
    source_ids = [t.source_id for t in transactions if t.source_id]
    existing_map: dict[str, Transaction] = {}
    if source_ids:
        result = await session.execute(
            select(Transaction).where(
                and_(
                    Transaction.household_id == household_id,
                    Transaction.source_id.in_(source_ids),
                )
            )
        )
        existing_map = {row.source_id: row for row in result.scalars()}

    inserted = updated = unchanged = 0

    for tx in transactions:
        data = _domain_to_orm_kwargs(household_id, tx)
        existing = existing_map.get(tx.source_id) if tx.source_id else None

        if existing is None:
            session.add(Transaction(**data))
            inserted += 1
            continue

        if _fields_differ(existing, data):
            for key, value in data.items():
                if key in ("household_id", "source_id"):
                    continue
                setattr(existing, key, value)
            updated += 1
        else:
            unchanged += 1

    await session.flush()
    return UpsertResult(inserted=inserted, updated=updated, unchanged=unchanged)


async def list_transactions(
    session: AsyncSession,
    household_id: str,
    *,
    start: date | None = None,
    end: date | None = None,
    limit: int = 100,
    offset: int = 0,
    exclude_transfers: bool = True,
    exclude_non_target: bool = True,
) -> tuple[list[Transaction], int]:
    """取引の一覧取得。戻り値は (rows, total_count)。"""
    conditions = [Transaction.household_id == household_id]
    if start is not None:
        conditions.append(Transaction.date >= start)
    if end is not None:
        conditions.append(Transaction.date <= end)
    if exclude_transfers:
        conditions.append(Transaction.is_transfer == False)  # noqa: E712
    if exclude_non_target:
        conditions.append(Transaction.is_target == True)  # noqa: E712

    base = select(Transaction).where(and_(*conditions))

    # total
    total_res = await session.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = int(total_res.scalar_one())

    rows_res = await session.execute(
        base.order_by(Transaction.date.desc(), Transaction.id.desc())
        .limit(limit).offset(offset)
    )
    rows = list(rows_res.scalars())
    return rows, total
