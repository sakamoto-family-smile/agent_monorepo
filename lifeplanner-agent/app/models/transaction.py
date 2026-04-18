"""
MF ME 取引レコードのドメインモデル。

DB スキーマは後続 Phase で追加するため、ここでは Pydantic の値オブジェクトとして定義する。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class TransactionKind(str, Enum):
    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"


class Transaction(BaseModel):
    """単一取引（MF CSV の1行に相当）。"""

    model_config = ConfigDict(frozen=True)

    source_id: str                # MF の ID カラム
    date: date
    content: str                  # 内容（店舗・明細）
    amount: Decimal               # 円単位 Decimal（支出は負、収入は正）
    account: str                  # 保有金融機関
    category: str                 # 大項目
    subcategory: str | None       # 中項目
    memo: str | None
    is_transfer: bool             # 振替取引か
    is_target: bool               # 計算対象フラグ

    @property
    def kind(self) -> TransactionKind:
        if self.is_transfer:
            return TransactionKind.TRANSFER
        return TransactionKind.EXPENSE if self.amount < 0 else TransactionKind.INCOME

    @property
    def absolute_amount(self) -> Decimal:
        return abs(self.amount)


class ImportResult(BaseModel):
    """CSV取込処理の結果サマリ。"""

    model_config = ConfigDict(frozen=True)

    source_file: str
    encoding: str
    total_rows: int
    imported: int
    skipped_transfer: int
    skipped_excluded: int        # 計算対象外（計算対象=0）
    skipped_invalid: int
    duplicates_in_file: int
    transactions: list[Transaction] = Field(default_factory=list)

    @property
    def income_total(self) -> Decimal:
        return sum(
            (t.amount for t in self.transactions if t.kind == TransactionKind.INCOME),
            start=Decimal("0"),
        )

    @property
    def expense_total(self) -> Decimal:
        return sum(
            (t.absolute_amount for t in self.transactions if t.kind == TransactionKind.EXPENSE),
            start=Decimal("0"),
        )

    @property
    def net(self) -> Decimal:
        return self.income_total - self.expense_total
