"""ライフイベント共通の型定義。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class EventCategory(str, Enum):
    """CashFlowDelta の分類。Simulator 側のグルーピングに利用。"""

    INCOME = "income"             # 給与変動・給付
    ONE_TIME = "one_time"         # 一時費用 (出産費用・住宅頭金など)
    RECURRING = "recurring"       # 毎年発生 (教育費・保育料・ローン返済)
    CHILD_BENEFIT = "child_benefit"  # 児童手当など政府給付


@dataclass(frozen=True)
class CashFlowDelta:
    """単一年度のキャッシュフロー差分 1 行。

    amount: 正 = 収入/給付 (income 増)、負 = 支出 (expense 増)
    year: 西暦
    category: 分類
    label: 人間可読なラベル (UI 表示、監査ログ用)
    """

    year: int
    amount: Decimal
    category: EventCategory
    label: str
