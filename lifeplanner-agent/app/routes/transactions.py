"""GET /api/transactions — 取引の一覧取得（ページング）。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from repositories.transaction import list_transactions
from services.auth import get_household_id
from services.database import get_session_dep

router = APIRouter(prefix="/api", tags=["transactions"])


class TransactionOut(BaseModel):
    id: int
    source_id: str
    date: date
    content: str
    amount: Decimal
    account: str
    category: str
    subcategory: str | None
    memo: str | None
    is_transfer: bool
    is_target: bool


class TransactionListResponse(BaseModel):
    household_id: str
    total: int
    offset: int
    limit: int
    items: list[TransactionOut]


@router.get("/transactions", response_model=TransactionListResponse)
async def list_transactions_endpoint(
    start: date | None = Query(default=None, description="from (inclusive)"),
    end: date | None = Query(default=None, description="to (inclusive)"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    include_transfers: bool = Query(default=False),
    include_non_target: bool = Query(default=False),
    household_id: str = Depends(get_household_id),
    session: AsyncSession = Depends(get_session_dep),
) -> TransactionListResponse:
    rows, total = await list_transactions(
        session,
        household_id,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
        exclude_transfers=not include_transfers,
        exclude_non_target=not include_non_target,
    )
    items = [
        TransactionOut(
            id=r.id,
            source_id=r.source_id,
            date=r.date,
            content=r.content,
            amount=r.amount,
            account=r.account,
            category=r.category,
            subcategory=r.subcategory,
            memo=r.memo,
            is_transfer=r.is_transfer,
            is_target=r.is_target,
        )
        for r in rows
    ]
    return TransactionListResponse(
        household_id=household_id,
        total=total,
        offset=offset,
        limit=limit,
        items=items,
    )
