"""
金額計算ユーティリティ。float を使わず Decimal で扱うことで端数誤差を防ぐ。
家計・税計算では 1 円未満は切り捨てが一般的なので、量子化を統一する。
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Final

_YEN_QUANT: Final[Decimal] = Decimal("1")


def to_yen(value: str | int | float | Decimal) -> Decimal:
    """
    任意の数値入力を「円」単位の Decimal に変換する。
    カンマ区切り・全角数字・ダブルクオート付きも許容。
    変換不能な場合は ValueError を送出する。
    """
    if isinstance(value, Decimal):
        return value.quantize(_YEN_QUANT, rounding=ROUND_DOWN)

    if isinstance(value, (int, float)):
        return Decimal(str(value)).quantize(_YEN_QUANT, rounding=ROUND_DOWN)

    if not isinstance(value, str):
        raise ValueError(f"Unsupported money input type: {type(value).__name__}")

    cleaned = (
        value.strip()
        .strip('"')
        .replace(",", "")
        .replace("，", "")
        .replace("￥", "")
        .replace("¥", "")
        .translate(str.maketrans("０１２３４５６７８９－＋", "0123456789-+"))
    )
    if cleaned in ("", "-", "+"):
        raise ValueError(f"Empty numeric value: {value!r}")

    try:
        return Decimal(cleaned).quantize(_YEN_QUANT, rounding=ROUND_DOWN)
    except InvalidOperation as e:
        raise ValueError(f"Invalid money literal: {value!r}") from e
