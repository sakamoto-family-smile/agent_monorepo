"""Phase 1.5: ImageStore (LRU + TTL) の挙動。"""

from __future__ import annotations

import time

from services.image_store import ImageStore


def test_put_get_roundtrip() -> None:
    store = ImageStore()
    iid = store.put(b"hello-png-bytes")
    assert isinstance(iid, str)
    item = store.get(iid)
    assert item is not None
    data, ct = item
    assert data == b"hello-png-bytes"
    assert ct == "image/png"


def test_get_returns_none_for_unknown_id() -> None:
    store = ImageStore()
    assert store.get("nonexistent") is None


def test_lru_evicts_oldest_when_full() -> None:
    store = ImageStore(max_entries=3)
    ids = [store.put(f"img{i}".encode()) for i in range(4)]
    # oldest (ids[0]) が evict される
    assert store.get(ids[0]) is None
    assert store.get(ids[1]) is not None
    assert store.get(ids[2]) is not None
    assert store.get(ids[3]) is not None


def test_ttl_expires() -> None:
    store = ImageStore(ttl_seconds=0)  # 即座に期限切れ
    iid = store.put(b"data")
    # tiny sleep で確実に過去になる
    time.sleep(0.01)
    assert store.get(iid) is None


def test_get_moves_to_end_on_access() -> None:
    """LRU: 古いエントリでも get すると end に移動して evict されにくい。"""
    store = ImageStore(max_entries=2)
    a = store.put(b"a")
    b = store.put(b"b")
    # a を access (新しい扱いになる)
    assert store.get(a) is not None
    # 新しい c を入れると、最古になっていた b が evict される
    c = store.put(b"c")
    assert store.get(b) is None
    assert store.get(a) is not None
    assert store.get(c) is not None
