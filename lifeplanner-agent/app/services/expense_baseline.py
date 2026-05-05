"""カテゴリ別生活費ベースラインの計算 (PR 1)。

取り込み済 transactions を集計し、`expense_baseline_by_category` を生成する。
simulator はこの dict を初期値として、各年で inflation 率を掛けて推移させる。

設計判断:
  - 「直近 12 ヶ月」を default 期間とする (短期過ぎると季節変動、長期過ぎると古い習慣)
  - `expense_type=='income'` は income 側に分類されるため除外
  - `is_transfer / is_target=False` (CSV importer で既にフラグ付け済) は除外
  - 0 円カテゴリは省略 (UI でゴミにならないように)
  - decimal 精度は yen 単位 (Numeric(14,0) と同じ)
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from models.db import Transaction
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

_ZERO = Decimal(0)
_DEFAULT_LOOKBACK_DAYS = 365


@dataclass(frozen=True)
class CategoryBaseline:
    """1 カテゴリ分のベースライン。"""

    category: str             # canonical_category (例: "food")
    expense_type: str         # "fixed" / "variable"
    annual_amount: Decimal    # 年額 (正の値、円)


@dataclass(frozen=True)
class ExpenseBaseline:
    """生活費ベースライン全体。simulator に渡す入力。"""

    period_start: date
    period_end: date
    by_category: dict[str, CategoryBaseline]

    @property
    def total_annual(self) -> Decimal:
        return sum((c.annual_amount for c in self.by_category.values()), _ZERO)

    def to_amounts_dict(self) -> dict[str, Decimal]:
        """simulator 用に {category: annual_amount} の dict を返す。"""
        return {k: v.annual_amount for k, v in self.by_category.items()}


async def compute_expense_baseline(
    session: AsyncSession,
    household_id: str,
    *,
    end: date | None = None,
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
) -> ExpenseBaseline:
    """直近 `lookback_days` 日間の transactions をカテゴリ別に集計して年額換算。

    end が None なら今日。lookback_days が 365 でない場合は年率換算する
    (例: 半年 (180 日) なら × (365 / 180))。
    """
    today = end or date.today()
    period_end = today
    period_start = today - timedelta(days=lookback_days)

    # `expense_type='income'` を除外 (給与等は simulator 側で扱う)
    stmt = (
        select(
            Transaction.canonical_category,
            Transaction.expense_type,
            func.sum(Transaction.amount).label("total"),
        )
        .where(
            and_(
                Transaction.household_id == household_id,
                Transaction.date >= period_start,
                Transaction.date <= period_end,
                Transaction.is_transfer == False,  # noqa: E712
                Transaction.is_target == True,  # noqa: E712
                Transaction.expense_type != "income",
            )
        )
        .group_by(Transaction.canonical_category, Transaction.expense_type)
    )
    result = await session.execute(stmt)

    by_category: dict[str, CategoryBaseline] = {}
    annualizer = Decimal(365) / Decimal(max(1, lookback_days))
    for canonical_category, expense_type, total in result.all():
        # transactions.amount は支出が負値で入っている想定 → 絶対値を年額に
        raw = Decimal(total or 0)
        if raw == _ZERO:
            continue
        annual = abs(raw) * annualizer
        # 0 円のカテゴリは UI でノイズなので捨てる
        if annual <= _ZERO:
            continue
        by_category[canonical_category] = CategoryBaseline(
            category=canonical_category,
            expense_type=expense_type or "variable",
            annual_amount=annual.quantize(Decimal(1)),  # 円単位
        )

    return ExpenseBaseline(
        period_start=period_start,
        period_end=period_end,
        by_category=by_category,
    )


def baseline_from_amounts(amounts: dict[str, Decimal]) -> ExpenseBaseline:
    """テスト / 手動入力用に、amounts dict から ExpenseBaseline を組み立てる。

    period_start/end はダミー (today)。expense_type は variable と仮定。
    """
    today = date.today()
    by_category = {
        cat: CategoryBaseline(category=cat, expense_type="variable", annual_amount=amount)
        for cat, amount in amounts.items()
        if amount > _ZERO
    }
    return ExpenseBaseline(period_start=today, period_end=today, by_category=by_category)


def empty_baseline() -> ExpenseBaseline:
    today = date.today()
    return ExpenseBaseline(period_start=today, period_end=today, by_category={})


def total_of(amounts: Iterable[Decimal]) -> Decimal:
    return sum(amounts, _ZERO)


__all__ = [
    "CategoryBaseline",
    "ExpenseBaseline",
    "baseline_from_amounts",
    "compute_expense_baseline",
    "empty_baseline",
]
