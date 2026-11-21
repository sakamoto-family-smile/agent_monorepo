"""所定スキーマ (請求書) と フィールド型レジストリ。

設計ガイド 4.5.4「型別接地ルール」に対応。各フィールド名を接地戦略を決める
``FieldType`` に対応づける (``FIELD_TYPES``)。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class FieldType(StrEnum):
    """接地・再検証の戦略を決めるフィールド型。

    - AMOUNT: 金額。語境界regex + 数値再検証(必須)。
    - NUMERIC: 数量。AMOUNT と同系だが通貨記号を持たない。
    - DATE: 日付。正規化後の完全一致。
    - CODE: 型番・ID。厳密完全一致 (取り違え致命的)。
    - NAME: 人名・組織名。fuzzy 一致。
    - ADDRESS: 住所。fuzzy 一致 (部分許容)。
    """

    AMOUNT = "amount"
    NUMERIC = "numeric"
    DATE = "date"
    CODE = "code"
    NAME = "name"
    ADDRESS = "address"


class LineItem(BaseModel):
    """請求明細 1 行。"""

    description: str
    quantity: int = Field(ge=0)
    unit_price: int = Field(ge=0)
    amount: int = Field(ge=0)

    @field_validator("amount")
    @classmethod
    def _amount_consistency(cls, v: int, info) -> int:
        # quantity * unit_price == amount を弱く要求 (生成データの健全性)。
        q = info.data.get("quantity")
        u = info.data.get("unit_price")
        if q is not None and u is not None and q * u != v:
            raise ValueError(f"line amount mismatch: {q}*{u} != {v}")
        return v


class Invoice(BaseModel):
    """請求書の所定スキーマ。gold record / 抽出ターゲット双方の正本。"""

    issuer_name: str
    issuer_address: str
    recipient_name: str
    invoice_no: str
    issue_date: str  # ISO 正規形 (YYYY-MM-DD)
    due_date: str
    line_items: list[LineItem]
    subtotal: int = Field(ge=0)
    tax: int = Field(ge=0)
    total: int = Field(ge=0)

    @field_validator("total")
    @classmethod
    def _total_consistency(cls, v: int, info) -> int:
        sub = info.data.get("subtotal")
        tax = info.data.get("tax")
        if sub is not None and tax is not None and sub + tax != v:
            raise ValueError(f"total mismatch: {sub}+{tax} != {v}")
        return v


# フィールドID (ドット記法で明細にも対応) → FieldType。
# 明細行は line_items[i].field の形で実行時に LINE_ITEM_FIELD_TYPES から解決する。
FIELD_TYPES: dict[str, FieldType] = {
    "issuer_name": FieldType.NAME,
    "issuer_address": FieldType.ADDRESS,
    "recipient_name": FieldType.NAME,
    "invoice_no": FieldType.CODE,
    "issue_date": FieldType.DATE,
    "due_date": FieldType.DATE,
    "subtotal": FieldType.AMOUNT,
    "tax": FieldType.AMOUNT,
    "total": FieldType.AMOUNT,
}

LINE_ITEM_FIELD_TYPES: dict[str, FieldType] = {
    "description": FieldType.NAME,
    "quantity": FieldType.NUMERIC,
    "unit_price": FieldType.AMOUNT,
    "amount": FieldType.AMOUNT,
}

# 帰属チェック (C2対策) でスロット入替を疑う相互排他フィールド群。
# 同じ値が複数スロットに接地し得るペアを明示する。
MUTUALLY_EXCLUSIVE_SLOTS: tuple[tuple[str, str], ...] = (
    ("issuer_name", "recipient_name"),
)


def field_type_of(field_id: str) -> FieldType:
    """field_id から FieldType を解決。明細は ``line_items[i].name`` 記法。"""
    if field_id.startswith("line_items[") and "]." in field_id:
        leaf = field_id.split("].", 1)[1]
        return LINE_ITEM_FIELD_TYPES[leaf]
    return FIELD_TYPES[field_id]


# テスト/型チェック向けのエクスポート別名。
InvoiceField = str
