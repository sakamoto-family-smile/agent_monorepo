"""GET /api/summary — 月次収支・カテゴリ別サマリ。"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth import get_household_id
from services.database import get_session_dep
from services.summary import compute_summary

router = APIRouter(prefix="/api", tags=["summary"])


class MonthlyOut(BaseModel):
    year_month: str
    income: Decimal
    expense: Decimal
    net: Decimal


class CategoryOut(BaseModel):
    category: str
    expense: Decimal
    count: int


class ExpenseTypeOut(BaseModel):
    fixed: Decimal
    variable: Decimal
    other: Decimal


class SummaryResponse(BaseModel):
    household_id: str
    start: date
    end: date
    total_income: Decimal
    total_expense: Decimal
    net: Decimal
    savings_rate: Decimal
    monthly: list[MonthlyOut]
    categories: list[CategoryOut]
    expense_types: ExpenseTypeOut


def _default_period() -> tuple[date, date]:
    """直近 12 ヶ月をデフォルトに。"""
    today = date.today()
    end = today
    start = (today.replace(day=1) - timedelta(days=365)).replace(day=1)
    return start, end


@router.get("/summary", response_model=SummaryResponse)
async def summary_endpoint(
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    top_categories: int = Query(default=10, ge=1, le=50),
    household_id: str = Depends(get_household_id),
    session: AsyncSession = Depends(get_session_dep),
) -> SummaryResponse:
    if start is None or end is None:
        ds, de = _default_period()
        start = start or ds
        end = end or de

    s = await compute_summary(
        session, household_id, start=start, end=end, top_categories=top_categories
    )
    return SummaryResponse(
        household_id=s.household_id,
        start=s.start,
        end=s.end,
        total_income=s.total_income,
        total_expense=s.total_expense,
        net=s.net,
        savings_rate=s.savings_rate,
        monthly=[MonthlyOut(**m.__dict__) for m in s.monthly],
        categories=[CategoryOut(**c.__dict__) for c in s.categories],
        expense_types=ExpenseTypeOut(
            fixed=s.expense_types.fixed,
            variable=s.expense_types.variable,
            other=s.expense_types.other,
        ),
    )
