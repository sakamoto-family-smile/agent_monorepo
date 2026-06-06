"""PROPOSAL-0011 P1: 一時 blob (チャート PNG / 全文 Markdown) のメモリ LRU+TTL store。

LINE の ImageMessage は `originalContentUrl` (HTTPS の公開 URL) を要求し、全文
レポートも「添付ファイル型」が無いため URL でホストする必要がある。MVP では
アプリのメモリ上に bytes を持ち、`/api/line/image/{id}.png` / `/api/line/report/{id}.md`
で配信する (永続配布が要れば Phase 2 で GCS 化)。

設計判断:
- LRU で最大 N 件 / 各エントリは TTL も持たせる (デフォルト 1 時間)
- 過剰アクセス防止のため key は `secrets.token_urlsafe` で推測不可
- Cloud Run の単一インスタンス (min/max=1) では問題なし。複数インスタンスでは
  「生成したインスタンス以外で叩かれると 404」になるが、LINE は通常生成直後に
  取りに来るので MVP は許容。永続化が要れば Phase 2 で GCS 署名 URL に置き換える。

piyolog-analytics の `ImageStore` を一般化 (content_type を任意化) して、画像と
全文 Markdown の両方を同じ実装で扱う。
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from config import settings


@dataclass(frozen=True)
class _BlobEntry:
    data: bytes
    content_type: str
    expires_at: float  # epoch seconds


class BlobStore:
    """thread-safe な LRU + TTL のメモリ blob store。"""

    def __init__(self, *, max_entries: int = 50, ttl_seconds: int = 3600) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._items: OrderedDict[str, _BlobEntry] = OrderedDict()

    def put(self, data: bytes, content_type: str) -> str:
        """blob を保存し推測不可な ID を返す。"""
        blob_id = secrets.token_urlsafe(16)
        expires_at = time.time() + self._ttl
        with self._lock:
            self._items[blob_id] = _BlobEntry(
                data=data, content_type=content_type, expires_at=expires_at
            )
            self._evict_locked()
        return blob_id

    def get(self, blob_id: str) -> tuple[bytes, str] | None:
        """ID で取り出す。期限切れ or 不在なら None。LRU で末尾に移動。"""
        with self._lock:
            entry = self._items.get(blob_id)
            if entry is None:
                return None
            if entry.expires_at < time.time():
                self._items.pop(blob_id, None)
                return None
            self._items.move_to_end(blob_id)
            return entry.data, entry.content_type

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def _evict_locked(self) -> None:
        """期限切れエントリを間引き、上限超えなら LRU で最古を削除する。"""
        now = time.time()
        expired = [k for k, v in self._items.items() if v.expires_at < now]
        for k in expired:
            self._items.pop(k, None)
        while len(self._items) > self._max_entries:
            self._items.popitem(last=False)


# ---------------------------------------------------------------------------
# プロセス内シングルトン (image / report で別インスタンス)
# ---------------------------------------------------------------------------

_image_store: BlobStore | None = None
_report_store: BlobStore | None = None


def get_image_store() -> BlobStore:
    global _image_store
    if _image_store is None:
        _image_store = BlobStore(
            max_entries=settings.image_store_max_entries,
            ttl_seconds=settings.image_store_ttl_seconds,
        )
    return _image_store


def get_report_store() -> BlobStore:
    global _report_store
    if _report_store is None:
        _report_store = BlobStore(
            max_entries=settings.report_store_max_entries,
            ttl_seconds=settings.report_store_ttl_seconds,
        )
    return _report_store


def reset_blob_stores() -> None:
    """テスト用 reset。"""
    global _image_store, _report_store
    _image_store = None
    _report_store = None


__all__ = [
    "BlobStore",
    "get_image_store",
    "get_report_store",
    "reset_blob_stores",
]
