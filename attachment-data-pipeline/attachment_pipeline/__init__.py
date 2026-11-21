"""非構造化テキスト → 構造化テーブル変換の高Precision抽出/検証パイプライン。

精度検証ハーネス。検証層は LLM 非依存・決定的で、抽出器は Protocol で
差し替え可能。詳細は docs/DESIGN.md。
"""

from __future__ import annotations

from .contracts import DecidedField, Decision, ExtractionResult
from .schema import FIELD_TYPES, FieldType, Invoice, InvoiceField

__all__ = [
    "DecidedField",
    "Decision",
    "ExtractionResult",
    "FIELD_TYPES",
    "FieldType",
    "Invoice",
    "InvoiceField",
]
