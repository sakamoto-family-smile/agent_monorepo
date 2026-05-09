"""SHA-256 ベースの差分検知。

ETL Job が前回取得時のハッシュを `etl_runs` テーブルに保存しておき、
今回取得分と比較。同一なら以降の処理をスキップ (Docling / embedding /
DB 書き込み) する。
"""

from __future__ import annotations

import hashlib


def compute_hash(content: bytes) -> str:
    """bytes の SHA-256 hex digest (64 文字、小文字)。"""
    return hashlib.sha256(content).hexdigest()


def has_changed(previous: str | None, current: str) -> bool:
    """前回ハッシュと今回ハッシュを比較。

    Args:
        previous: 前回取得時のハッシュ。初回取得なら None。
        current: 今回取得時のハッシュ。

    Returns:
        変更があれば True (= ETL を実行する)。
        previous が None の場合は常に True (初回 = 全件処理)。
    """
    if previous is None:
        return True
    return previous.lower() != current.lower()
