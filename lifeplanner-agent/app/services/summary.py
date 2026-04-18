"""
家計サマリ集計。

- 月別の収入・支出・ネット
- カテゴリ別（大項目）支出合計 Top N
- 期間は呼び出し側から指定。振替・対象外は除外。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, case, cast, func, select
from sqlalchemy import String as SaString
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import Transaction


@dataclass(frozen=True)
class MonthlyBreakdown:
    year_month: str  # "YYYY-MM"
    income: Decimal
    expense: Decimal
    net: Decimal


@dataclass(frozen=True)
class CategoryBreakdown:
    category: str
    expense: Decimal
    count: int


@dataclass(frozen=True)
class ExpenseTypeBreakdown:
    """固定費 / 変動費 の分解。"""

    fixed: Decimal
    variable: Decimal
    other: Decimal  # expense_type 未設定 or income 扱い以外

    @property
    def total(self) -> Decimal:
        return self.fixed + self.variable + self.other


@dataclass(frozen=True)
class Summary:
    household_id: str
    start: date
    end: date
    total_income: Decimal
    total_expense: Decimal
    net: Decimal
    savings_rate: Decimal  # net / total_income (収入 0 のときは 0)
    monthly: list[MonthlyBreakdown]
    categories: list[CategoryBreakdown]
    expense_types: ExpenseTypeBreakdown


def _year_month_expr(dialect: str):
    """DB 別の year_month 抽出式。"""
    if dialect == "sqlite":
        return func.strftime("%Y-%m", Transaction.date)
    # postgres / others
    return func.to_char(Transaction.date, "YYYY-MM")


async def compute_summary(
    session: AsyncSession,
    household_id: str,
    *,
    start: date,
    end: date,
    top_categories: int = 10,
) -> Summary:
    conditions = and_(
        Transaction.household_id == household_id,
        Transaction.is_transfer == False,  # noqa: E712
        Transaction.is_target == True,     # noqa: E712
        Transaction.date >= start,
        Transaction.date <= end,
    )

    dialect = session.bind.dialect.name if session.bind else "sqlite"

    # 収入・支出合計（amount の符号で判定）
    income_expr = func.coalesce(
        func.sum(case((Transaction.amount > 0, Transaction.amount), else_=0)), 0
    )
    expense_expr = func.coalesce(
        func.sum(case((Transaction.amount < 0, -Transaction.amount), else_=0)), 0
    )

    totals = await session.execute(
        select(income_expr, expense_expr).where(conditions)
    )
    inc, exp = totals.one()
    total_income = Decimal(inc or 0)
    total_expense = Decimal(exp or 0)

    # 月別
    ym = _year_month_expr(dialect).label("ym")
    monthly_res = await session.execute(
        select(ym, income_expr.label("inc"), expense_expr.label("exp"))
        .where(conditions)
        .group_by(ym)
        .order_by(ym)
    )
    monthly = [
        MonthlyBreakdown(
            year_month=str(row.ym),
            income=Decimal(row.inc or 0),
            expense=Decimal(row.exp or 0),
            net=Decimal(row.inc or 0) - Decimal(row.exp or 0),
        )
        for row in monthly_res
    ]

    # カテゴリ別支出（canonical_category 優先、fallback として大項目）
    cat_res = await session.execute(
        select(
            Transaction.canonical_category.label("cat"),
            func.coalesce(func.sum(-Transaction.amount), 0).label("exp"),
            func.count().label("n"),
        )
        .where(and_(conditions, Transaction.amount < 0))
        .group_by(Transaction.canonical_category)
        .order_by(func.sum(-Transaction.amount).desc())
        .limit(top_categories)
    )
    categories = [
        CategoryBreakdown(
            category=row.cat,
            expense=Decimal(row.exp or 0),
            count=int(row.n),
        )
        for row in cat_res
    ]

    # 固定費 / 変動費 分解
    type_res = await session.execute(
        select(
            Transaction.expense_type.label("et"),
            func.coalesce(func.sum(-Transaction.amount), 0).label("exp"),
        )
        .where(and_(conditions, Transaction.amount < 0))
        .group_by(Transaction.expense_type)
    )
    type_map: dict[str, Decimal] = {row.et: Decimal(row.exp or 0) for row in type_res}
    expense_types = ExpenseTypeBreakdown(
        fixed=type_map.get("fixed", Decimal(0)),
        variable=type_map.get("variable", Decimal(0)),
        other=sum(
            (v for k, v in type_map.items() if k not in ("fixed", "variable")),
            Decimal(0),
        ),
    )

    net = total_income - total_expense
    savings_rate = (net / total_income) if total_income > 0 else Decimal(0)

    return Summary(
        household_id=household_id,
        start=start,
        end=end,
        total_income=total_income,
        total_expense=total_expense,
        net=net,
        savings_rate=savings_rate,
        monthly=monthly,
        categories=categories,
        expense_types=expense_types,
    )
