"""
ファイルエンコーディングの検出。

MF ME のエクスポートは CP932 (Shift-JIS) が既定だが、ユーザーが手動で UTF-8
再保存するケースもあるため自動判定する。
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from charset_normalizer import from_bytes

# MF ME で確認したエンコーディング優先順序
_PREFERRED: Final[tuple[str, ...]] = ("utf-8-sig", "utf-8", "cp932", "shift_jis")


def detect_encoding(data: bytes, *, sample_size: int = 8192) -> str:
    """
    バイト列から最も確度の高いエンコーディング名を返す。
    先頭 `sample_size` バイトのみを検査対象とする。

    優先順序:
      1. 優先リスト内で完全デコード可能な最初のもの
      2. charset_normalizer の推定結果
      3. どれも失敗したら "utf-8"（呼び出し側で errors='replace' 等を想定）
    """
    sample = data[:sample_size]

    for enc in _PREFERRED:
        try:
            sample.decode(enc)
        except UnicodeDecodeError:
            continue
        else:
            return enc

    result = from_bytes(sample).best()
    if result is not None:
        return result.encoding

    return "utf-8"


def read_text_auto(path: str | Path) -> tuple[str, str]:
    """
    ファイルを自動判定エンコーディングで読み込む。
    戻り値は (本文, 検出エンコーディング名)。
    """
    raw = Path(path).read_bytes()
    enc = detect_encoding(raw)
    return raw.decode(enc, errors="replace"), enc
