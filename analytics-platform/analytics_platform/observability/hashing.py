"""`sha256:<hex>` 形式のハッシュ生成ユーティリティ。

設計書 §6.2 `content_hash` の prefix 強制。呼び出し側の詰め忘れを防ぐためここに集約。
"""

from __future__ import annotations

import hashlib

_PREFIX = "sha256:"


def sha256_prefixed(data: bytes | str) -> str:
    """バイト列 or 文字列から `sha256:<hex>` を返す。"""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return _PREFIX + hashlib.sha256(data).hexdigest()


def strip_prefix(value: str) -> str:
    """`sha256:<hex>` → `<hex>`。prefix が無ければそのまま返す。"""
    if value.startswith(_PREFIX):
        return value[len(_PREFIX) :]
    return value
