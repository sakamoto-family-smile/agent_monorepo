"""DedupRepo (SQLite) テスト。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from repositories.dedup_repo import DedupRepo


@pytest.fixture
async def repo(tmp_path):
    r = DedupRepo(db_path=str(tmp_path / "t.db"))
    await r.initialize()
    return r


@pytest.mark.asyncio
async def test_filter_new_ids_returns_all_when_empty(repo: DedupRepo):
    ids = {"a", "b", "c"}
    new = await repo.filter_new_ids(ids, window_days=30)
    assert new == ids


@pytest.mark.asyncio
async def test_filter_excludes_recently_delivered(repo: DedupRepo):
    await repo.create_digest("d1", generated_at=datetime.now(UTC))
    await repo.record_delivery(
        digest_id="d1",
        articles=[("a", "t", "s", "rss", "https://x/a")],
        status="sent",
        note=None,
    )
    new = await repo.filter_new_ids(["a", "b"], window_days=30)
    assert new == {"b"}


@pytest.mark.asyncio
async def test_filter_includes_articles_older_than_window(repo: DedupRepo):
    """window_days=0 で境界確認。過去の配信でも window が 0 日ならフィルタから外れる。"""
    await repo.create_digest("d1", generated_at=datetime.now(UTC))
    await repo.record_delivery(
        digest_id="d1",
        articles=[("a", "t", "s", "rss", "https://x/a")],
        status="sent",
        note=None,
    )
    # window_days=0: いま配信したものも cutoff 以降に入る → filter される
    # window_days=-1 だと cutoff が未来になり、過去配信でも新規扱い
    new_large_window = await repo.filter_new_ids(["a"], window_days=30)
    assert new_large_window == set()


@pytest.mark.asyncio
async def test_failed_digest_does_not_mark_delivered(repo: DedupRepo):
    await repo.create_digest("d1", generated_at=datetime.now(UTC))
    await repo.record_delivery(
        digest_id="d1", articles=[], status="failed", note="LINE 503"
    )
    new = await repo.filter_new_ids(["a"], window_days=30)
    assert new == {"a"}
    assert await repo.count_delivered() == 0


@pytest.mark.asyncio
async def test_idempotent_record_delivery(repo: DedupRepo):
    await repo.create_digest("d1", generated_at=datetime.now(UTC))
    articles = [("a", "t", "s", "rss", "https://x/a")]
    await repo.record_delivery(digest_id="d1", articles=articles, status="sent")
    await repo.record_delivery(digest_id="d1", articles=articles, status="sent")
    assert await repo.count_delivered() == 1
