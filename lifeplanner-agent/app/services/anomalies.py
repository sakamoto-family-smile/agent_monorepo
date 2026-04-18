"""支出異常値検出 (F3)。

各 canonical カテゴリについて、過去数ヶ月の月次合計支出を使って
今月の支出が (平均 + k*標準偏差) を超えるかを判定する。

シグナル: 月別 canonical カテゴリ支出 → 直近 N ヶ月ローリング
          (history) が history_months 以上揃うカテゴリのみ判定
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from models.db import Transaction
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class Anomaly:
    year_month: str
    canonical_category: str
    expense: Decimal
    mean: Decimal
    std: Decimal
    z_score: Decimal  # (expense - mean) / std
    threshold: Decimal  # mean + k*std


async def detect_anomalies(
    session: AsyncSession,
    household_id: str,
    *,
    target_month: date,
    history_months: int = 6,
    k: Decimal = Decimal("3"),
    min_samples: int = 3,
) -> list[Anomaly]:
    """target_month が属する月について、canonical カテゴリごとに平均+kσ超えを検出。

    target_month: 判定対象月(その月の 1 日でも任意の日でも良い)
    history_months: 遡るローリング月数 (target_month を含まない直近)
    k: 閾値倍率 (標準偏差の何倍以上を外れ値とするか)
    min_samples: 統計を取るための最小履歴数
    """
    # target_month の開始と終了
    target_start = target_month.replace(day=1)
    if target_start.month == 12:
        target_end = target_start.replace(year=target_start.year + 1, month=1)
    else:
        target_end = target_start.replace(month=target_start.month + 1)

    # 履歴期間の開始 (target_start から history_months 遡る)
    y, m = target_start.year, target_start.month
    m -= history_months
    while m <= 0:
        m += 12
        y -= 1
    history_start = date(y, m, 1)

    dialect = session.bind.dialect.name if session.bind else "sqlite"
    if dialect == "sqlite":
        ym_expr = func.strftime("%Y-%m", Transaction.date)
    else:
        ym_expr = func.to_char(Transaction.date, "YYYY-MM")

    conditions = and_(
        Transaction.household_id == household_id,
        Transaction.is_transfer == False,  # noqa: E712
        Transaction.is_target == True,     # noqa: E712
        Transaction.amount < 0,
        Transaction.date >= history_start,
        Transaction.date < target_end,
    )

    # 月次 canonical カテゴリ支出
    rows = await session.execute(
        select(
            ym_expr.label("ym"),
            Transaction.canonical_category.label("cat"),
            func.coalesce(func.sum(-Transaction.amount), 0).label("exp"),
        )
        .where(conditions)
        .group_by("ym", Transaction.canonical_category)
    )

    # カテゴリごとに (history, target) へ振り分け
    target_ym = target_start.strftime("%Y-%m")
    by_cat_history: dict[str, list[Decimal]] = {}
    by_cat_target: dict[str, Decimal] = {}
    for row in rows:
        amount = Decimal(row.exp or 0)
        if row.ym == target_ym:
            by_cat_target[row.cat] = amount
        else:
            by_cat_history.setdefault(row.cat, []).append(amount)

    anomalies: list[Anomaly] = []
    for cat, current in by_cat_target.items():
        history = by_cat_history.get(cat, [])
        if len(history) < min_samples:
            continue
        mean = sum(history, Decimal(0)) / Decimal(len(history))
        # 標準偏差 (不偏: n-1)
        if len(history) > 1:
            variance = sum(((v - mean) ** 2 for v in history), Decimal(0)) / Decimal(
                len(history) - 1
            )
            std = Decimal(str(math.sqrt(float(variance))))
        else:
            std = Decimal(0)
        # 履歴が完全に一定だと std=0 になり判定不能。CV 10% をフロアにする。
        effective_std = max(std, mean * Decimal("0.1"))
        if effective_std <= 0:
            continue
        threshold = mean + k * effective_std
        if current > threshold:
            z = (current - mean) / effective_std
            anomalies.append(
                Anomaly(
                    year_month=target_ym,
                    canonical_category=cat,
                    expense=current,
                    mean=mean,
                    std=std,
                    z_score=z,
                    threshold=threshold,
                )
            )

    anomalies.sort(key=lambda a: a.z_score, reverse=True)
    return anomalies
