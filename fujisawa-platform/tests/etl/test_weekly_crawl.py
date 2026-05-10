"""weekly_crawl_etl のテスト。

藤沢市 sitemap.xml を起点に各 URL を polite fetch → 本文抽出 → embed → upsert する
ETL 全体パスを mock で通す。実 DB / 実ネットワーク / 実 embedding は使わない。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx

from fujisawa_platform.crawler import PoliteFetcher, PoliteFetcherConfig
from fujisawa_platform.etl._runner import EtlRunResult
from fujisawa_platform.etl.weekly_crawl import (
    CrawlOutcome,
    crawl_and_index,
    run_weekly_crawl,
)
from fujisawa_platform.knowledge_base import MockEmbeddingClient
from fujisawa_platform.knowledge_base.store import PageDocument

_SITEMAP_URL = "https://www.city.fujisawa.kanagawa.jp/sitemap.xml"


def _sitemap_xml(urls: Iterable[str]) -> bytes:
    items = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{items}</urlset>"
    ).encode()


class _RecordingStore:
    """upsert / search を呼ばれた page_id を記録する Mock Store。"""

    def __init__(self) -> None:
        self.upserted: list[PageDocument] = []

    async def upsert_page(self, page: PageDocument) -> None:
        self.upserted.append(page)


@pytest.fixture
def fetcher_config() -> PoliteFetcherConfig:
    return PoliteFetcherConfig(
        user_agent="fujisawa-etl-test/0.1 (https://example.com)",
        min_interval_sec=0.001,
        max_retries=1,
        backoff_base_sec=0.001,
    )


# ─────────────────────────────────────────────────────────────────────
# crawl_and_index (主要ロジック)
# ─────────────────────────────────────────────────────────────────────


class TestCrawlAndIndex:
    @pytest.mark.asyncio
    @respx.mock
    async def test_indexes_sitemap_urls_into_store(
        self, fetcher_config: PoliteFetcherConfig
    ) -> None:
        respx.get(_SITEMAP_URL).mock(
            return_value=httpx.Response(
                200,
                content=_sitemap_xml(
                    [
                        "https://www.city.fujisawa.kanagawa.jp/page-a",
                        "https://www.city.fujisawa.kanagawa.jp/page-b",
                    ]
                ),
            )
        )
        respx.get("https://www.city.fujisawa.kanagawa.jp/page-a").mock(
            return_value=httpx.Response(
                200,
                text="<html><body><main><h1>A</h1><p>本文 A。</p></main></body></html>",
            )
        )
        respx.get("https://www.city.fujisawa.kanagawa.jp/page-b").mock(
            return_value=httpx.Response(
                200,
                text="<html><body><main><h1>B</h1><p>本文 B。</p></main></body></html>",
            )
        )
        store = _RecordingStore()

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_index(
                sitemap_url=_SITEMAP_URL,
                fetcher=fetcher,
                embedder=MockEmbeddingClient(),
                store=store,  # type: ignore[arg-type]
                now=lambda: datetime(2026, 5, 10, 3, 0, tzinfo=UTC),
            )

        assert outcome.rows_written == 2
        assert outcome.skipped_not_modified == 0
        assert {p.url.unicode_string().rstrip("/") for p in store.upserted} == {
            "https://www.city.fujisawa.kanagawa.jp/page-a",
            "https://www.city.fujisawa.kanagawa.jp/page-b",
        }
        # page_id は URL の SHA-256 derived (詳細は実装の hash_url に従う)
        assert all(len(p.page_id) == 64 for p in store.upserted)

    @pytest.mark.asyncio
    @respx.mock
    async def test_skips_304_not_modified(self, fetcher_config: PoliteFetcherConfig) -> None:
        respx.get(_SITEMAP_URL).mock(
            return_value=httpx.Response(
                200,
                content=_sitemap_xml(["https://www.city.fujisawa.kanagawa.jp/page-a"]),
            )
        )
        respx.get("https://www.city.fujisawa.kanagawa.jp/page-a").mock(
            return_value=httpx.Response(304),
        )
        store = _RecordingStore()

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_index(
                sitemap_url=_SITEMAP_URL,
                fetcher=fetcher,
                embedder=MockEmbeddingClient(),
                store=store,  # type: ignore[arg-type]
                # If-Modified-Since を立てる前回取得日時 (304 をテストで誘発するため)
                if_modified_since=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
            )

        assert outcome.rows_written == 0
        assert outcome.skipped_not_modified == 1
        assert store.upserted == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_skips_url_when_extracted_text_is_empty(
        self, fetcher_config: PoliteFetcherConfig
    ) -> None:
        respx.get(_SITEMAP_URL).mock(
            return_value=httpx.Response(
                200,
                content=_sitemap_xml(["https://www.city.fujisawa.kanagawa.jp/empty"]),
            )
        )
        respx.get("https://www.city.fujisawa.kanagawa.jp/empty").mock(
            return_value=httpx.Response(
                200,
                text="<html><body><main></main></body></html>",
            )
        )
        store = _RecordingStore()

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_index(
                sitemap_url=_SITEMAP_URL,
                fetcher=fetcher,
                embedder=MockEmbeddingClient(),
                store=store,  # type: ignore[arg-type]
            )

        assert outcome.rows_written == 0
        assert outcome.skipped_empty == 1
        assert store.upserted == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_continues_after_per_url_failure(
        self, fetcher_config: PoliteFetcherConfig
    ) -> None:
        """個別 URL が 4xx 等で fail しても、他 URL の処理は続行される。"""
        respx.get(_SITEMAP_URL).mock(
            return_value=httpx.Response(
                200,
                content=_sitemap_xml(
                    [
                        "https://www.city.fujisawa.kanagawa.jp/ok",
                        "https://www.city.fujisawa.kanagawa.jp/missing",
                    ]
                ),
            )
        )
        respx.get("https://www.city.fujisawa.kanagawa.jp/ok").mock(
            return_value=httpx.Response(
                200,
                text="<html><body><main><p>ok page</p></main></body></html>",
            )
        )
        respx.get("https://www.city.fujisawa.kanagawa.jp/missing").mock(
            return_value=httpx.Response(404),
        )
        store = _RecordingStore()

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_index(
                sitemap_url=_SITEMAP_URL,
                fetcher=fetcher,
                embedder=MockEmbeddingClient(),
                store=store,  # type: ignore[arg-type]
            )

        assert outcome.rows_written == 1
        assert outcome.failed_urls == 1
        assert len(store.upserted) == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_dry_run_does_not_call_store(self, fetcher_config: PoliteFetcherConfig) -> None:
        respx.get(_SITEMAP_URL).mock(
            return_value=httpx.Response(
                200,
                content=_sitemap_xml(["https://www.city.fujisawa.kanagawa.jp/page-a"]),
            )
        )
        respx.get("https://www.city.fujisawa.kanagawa.jp/page-a").mock(
            return_value=httpx.Response(
                200,
                text="<html><body><main><p>x</p></main></body></html>",
            )
        )
        store = _RecordingStore()

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_index(
                sitemap_url=_SITEMAP_URL,
                fetcher=fetcher,
                embedder=MockEmbeddingClient(),
                store=store,  # type: ignore[arg-type]
                dry_run=True,
            )

        # dry-run は store を叩かないが、parse 結果はカウントする
        assert outcome.rows_written == 1
        assert store.upserted == []


# ─────────────────────────────────────────────────────────────────────
# run_weekly_crawl (Cloud Run Job entrypoint)
# ─────────────────────────────────────────────────────────────────────


class _FakeRunsRepo:
    def __init__(self) -> None:
        self.starts: list[dict[str, Any]] = []
        self.finishes: list[dict[str, Any]] = []

    async def start_run(self, **kwargs: Any) -> None:
        self.starts.append(kwargs)

    async def finish_run(self, **kwargs: Any) -> None:
        self.finishes.append(kwargs)

    async def recent_runs(self, job_name: str, *, limit: int = 5) -> list[Any]:
        return []


class TestRunWeeklyCrawl:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_success_result(self, fetcher_config: PoliteFetcherConfig) -> None:
        respx.get(_SITEMAP_URL).mock(
            return_value=httpx.Response(
                200,
                content=_sitemap_xml(["https://www.city.fujisawa.kanagawa.jp/page-a"]),
            )
        )
        respx.get("https://www.city.fujisawa.kanagawa.jp/page-a").mock(
            return_value=httpx.Response(
                200,
                text="<html><body><main><p>本文</p></main></body></html>",
            )
        )
        store = _RecordingStore()
        repo = _FakeRunsRepo()

        result = await run_weekly_crawl(
            sitemap_url=_SITEMAP_URL,
            fetcher_config=fetcher_config,
            embedder=MockEmbeddingClient(),
            store=store,  # type: ignore[arg-type]
            runs_repo=repo,  # type: ignore[arg-type]
            run_id="weekly_crawl_etl-20260510-0300",
            now=lambda: datetime(2026, 5, 10, 3, 0, tzinfo=UTC),
        )

        assert isinstance(result, EtlRunResult)
        assert result.status == "success"
        assert result.rows_written == 1
        assert len(repo.finishes) == 1
        assert repo.finishes[0]["status"] == "success"


class TestCrawlOutcomeModel:
    def test_frozen(self) -> None:
        outcome = CrawlOutcome(
            rows_written=10,
            skipped_not_modified=2,
            skipped_empty=0,
            failed_urls=1,
            sitemap_hash="a" * 64,
        )
        with pytest.raises(Exception):
            outcome.rows_written = 99  # type: ignore[misc]
