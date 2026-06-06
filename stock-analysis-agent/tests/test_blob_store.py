"""BlobStore (チャート PNG / 全文 Markdown の一時 LRU+TTL store) の unit テスト。"""

from __future__ import annotations

import time

import pytest

from services.blob_store import (
    BlobStore,
    get_image_store,
    get_report_store,
    reset_blob_stores,
)


def test_put_then_get_roundtrip():
    store = BlobStore(max_entries=10, ttl_seconds=60)
    blob_id = store.put(b"hello", "text/markdown")
    got = store.get(blob_id)
    assert got == (b"hello", "text/markdown")


def test_get_unknown_id_returns_none():
    store = BlobStore(max_entries=10, ttl_seconds=60)
    assert store.get("nope") is None


def test_ids_are_unguessable_and_unique():
    store = BlobStore(max_entries=10, ttl_seconds=60)
    ids = {store.put(b"x", "image/png") for _ in range(20)}
    assert len(ids) == 20
    assert all(len(i) >= 16 for i in ids)


def test_ttl_expiry_returns_none():
    store = BlobStore(max_entries=10, ttl_seconds=0)
    blob_id = store.put(b"data", "image/png")
    time.sleep(0.01)
    assert store.get(blob_id) is None


def test_lru_eviction_drops_oldest():
    store = BlobStore(max_entries=2, ttl_seconds=60)
    a = store.put(b"a", "image/png")
    b = store.put(b"b", "image/png")
    c = store.put(b"c", "image/png")  # a を押し出す
    assert store.get(a) is None
    assert store.get(b) is not None
    assert store.get(c) is not None


def test_zero_max_entries_rejected():
    with pytest.raises(ValueError):
        BlobStore(max_entries=0)


def test_image_and_report_singletons_are_distinct():
    reset_blob_stores()
    assert get_image_store() is get_image_store()
    assert get_report_store() is get_report_store()
    assert get_image_store() is not get_report_store()
    reset_blob_stores()
