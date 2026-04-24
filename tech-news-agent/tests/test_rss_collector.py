"""RSS Collector テスト (httpx をモック注入)。"""

from __future__ import annotations

import pytest
from collectors.rss import fetch_all, fetch_source
from conftest import load_fixture_bytes
from services.source_config import RssSourceConfig


async def _stub_fetch(url: str) -> bytes:
    return load_fixture_bytes("sample_feed.xml")


@pytest.mark.asyncio
async def test_fetch_source_parses_rss_entries():
    src = RssSourceConfig(name="sample", url="https://x/feed", priority=3, weight=1.5)
    articles = await fetch_source(src, http_fetch=_stub_fetch)
    assert len(articles) == 2

    titles = {a.title for a in articles}
    assert "BigQuery Iceberg Integration Now GA" in titles
    # URL normalizer で utm 除去 + 末尾スラッシュ除去が行われている
    url_norms = {a.url_normalized for a in articles}
    assert "https://example.com/blog/bq-iceberg-ga" in url_norms
    assert "https://example.com/blog/dbt-cloud-pricing" in url_norms


@pytest.mark.asyncio
async def test_article_id_is_stable_across_fetch():
    src = RssSourceConfig(name="sample", url="https://x/feed", priority=3, weight=1.5)
    a1 = await fetch_source(src, http_fetch=_stub_fetch)
    a2 = await fetch_source(src, http_fetch=_stub_fetch)
    ids1 = {a.article_id for a in a1}
    ids2 = {a.article_id for a in a2}
    assert ids1 == ids2
    assert len(ids1) == 2   # 正規化後の URL が異なる 2 記事


@pytest.mark.asyncio
async def test_fetch_all_swallows_per_source_errors():
    """1 ソースが例外を投げても他ソースの結果は戻る。"""

    async def failing_fetch(url: str) -> bytes:
        if "bad" in url:
            raise RuntimeError("network down")
        return load_fixture_bytes("sample_feed.xml")

    sources = [
        RssSourceConfig(name="ok", url="https://x/feed", priority=3, weight=1.5),
        RssSourceConfig(name="bad", url="https://x/bad", priority=3, weight=1.5),
    ]
    articles = await fetch_all(sources, http_fetch=failing_fetch)
    # ok ソースの 2 件だけ返る
    assert len(articles) == 2
    assert all(a.source_name == "ok" for a in articles)
