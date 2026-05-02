"""Phase 1.5: 一時画像のメモリ LRU ストア。

LINE は ImageMessage で `originalContentUrl` (HTTPS の公開 URL) を要求する。
Phase 1.5 ではアプリのメモリ上に PNG bytes を持ち、`/api/line/image/{id}.png`
で配信する (Phase 4 で GCS Signed URL に置き換え予定)。

設計判断:
- LRU で最大 50 枚 / 各エントリは TTL も持たせる (デフォルト 1 時間)
- 過剰アクセス防止のため key は uuid 推測不可
- Cloud Run の単一インスタンスでは問題なし。複数インスタンスでは
  「画像を生成したインスタンス以外で叩かれると 404」になる。LINE は通常
  生成直後にすぐ取りに来るので Phase 1.5 は許容。Phase 4 で GCS 化で解消。
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass


@dataclass(frozen=True)
class _ImageEntry:
    data: bytes
    content_type: str
    expires_at: float  # epoch seconds


class ImageStore:
    """thread-safe な LRU + TTL メモリ store。

    複数 worker で動く Cloud Run 1 instance 内ではプロセス内 LRU で十分。
    """

    def __init__(self, *, max_entries: int = 50, ttl_seconds: int = 3600) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._items: OrderedDict[str, _ImageEntry] = OrderedDict()

    def put(self, data: bytes, content_type: str = "image/png") -> str:
        """画像を保存し ID を返す。"""
        image_id = secrets.token_urlsafe(16)
        expires_at = time.time() + self._ttl
        with self._lock:
            self._items[image_id] = _ImageEntry(
                data=data, content_type=content_type, expires_at=expires_at
            )
            self._evict_locked()
        return image_id

    def get(self, image_id: str) -> tuple[bytes, str] | None:
        """ID で取り出す。期限切れ or 不在なら None。LRU で末尾に移動。"""
        with self._lock:
            entry = self._items.get(image_id)
            if entry is None:
                return None
            if entry.expires_at < time.time():
                # 期限切れ → 削除
                self._items.pop(image_id, None)
                return None
            self._items.move_to_end(image_id)
            return entry.data, entry.content_type

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def _evict_locked(self) -> None:
        """先頭から期限切れエントリを削除し、上限超えなら LRU で末尾を残す。"""
        now = time.time()
        # 期限切れを先頭から間引く (insertion order ≒ access order の近似)
        expired = [k for k, v in self._items.items() if v.expires_at < now]
        for k in expired:
            self._items.pop(k, None)
        # 上限超え → 最古 (head) から削除
        while len(self._items) > self._max_entries:
            self._items.popitem(last=False)


# プロセス内シングルトン (FastAPI app に inject せず module-level でも良いが、
# テストで差し替えやすいように getter を提供)
_default_store: ImageStore | None = None


def get_image_store() -> ImageStore:
    global _default_store
    if _default_store is None:
        _default_store = ImageStore()
    return _default_store


def reset_image_store() -> None:
    """テスト用 reset。"""
    global _default_store
    _default_store = None


__all__ = [
    "ImageStore",
    "get_image_store",
    "reset_image_store",
]
