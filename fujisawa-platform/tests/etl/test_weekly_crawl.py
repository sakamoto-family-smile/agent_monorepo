"""weekly_crawl_etl のテスト (差分 crawl 版、 2026-05-21 改訂)。

藤沢市 sitemap.xml を起点に各 URL の HEAD で last_modified を取得 → DB と比較 →
更新がある URL のみ GET → 本文抽出 → embed → upsert する ETL 全体パスを mock で通す。
実 DB / 実ネットワーク / 実 embedding は使わない。
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
    """upsert と get_last_modified_map を観測する Mock Store。"""

    def __init__(
        self, *, last_modified_map: dict[str, datetime | None] | None = None
    ) -> None:
        self.upserted: list[PageDocument] = []
        self._last_modified_map: dict[str, datetime | None] = last_modified_map or {}
        self.get_calls: list[list[str]] = []

    async def upsert_page(self, page: PageDocument) -> None:
        self.upserted.append(page)

    async def get_last_modified_map(
        self, urls: list[str]
    ) -> dict[str, datetime | None]:
        self.get_calls.append(list(urls))
        return {u: self._last_modified_map[u] for u in urls if u in self._last_modified_map}


@pytest.fixture
def fetcher_config() -> PoliteFetcherConfig:
    return PoliteFetcherConfig(
        user_agent="fujisawa-etl-test/0.1 (https://example.com)",
        min_interval_sec=0.001,
        min_interval_sec_head=0.001,
        max_retries=1,
        backoff_base_sec=0.001,
    )


# ─────────────────────────────────────────────────────────────────────
# crawl_and_index (主要ロジック)
# ─────────────────────────────────────────────────────────────────────


class TestCrawlAndIndexInitialRun:
    """DB が空 (初回 full crawl) のときの挙動。 HEAD は呼ばれず全件 GET。"""

    @pytest.mark.asyncio
    @respx.mock
    async def test_initial_crawl_fetches_all_urls_without_head(
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
        head_a = respx.head("https://www.city.fujisawa.kanagawa.jp/page-a")
        head_b = respx.head("https://www.city.fujisawa.kanagawa.jp/page-b")
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
        store = _RecordingStore(last_modified_map={})  # DB empty

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_index(
                sitemap_url=_SITEMAP_URL,
                fetcher=fetcher,
                embedder=MockEmbeddingClient(),
                store=store,
                now=lambda: datetime(2026, 5, 10, 3, 0, tzinfo=UTC),
            )

        assert outcome.rows_written == 2
        assert outcome.skipped_unchanged == 0
        assert outcome.head_checks == 0  # 初回は HEAD を呼ばない
        assert head_a.called is False
        assert head_b.called is False
        assert len(store.upserted) == 2


class TestCrawlAndIndexIncremental:
    """DB に既存ページ有りのときの差分 crawl 挙動。"""

    @pytest.mark.asyncio
    @respx.mock
    async def test_skips_unchanged_when_head_lastmodified_not_newer(
        self, fetcher_config: PoliteFetcherConfig
    ) -> None:
        url = "https://www.city.fujisawa.kanagawa.jp/page-a"
        respx.get(_SITEMAP_URL).mock(
            return_value=httpx.Response(200, content=_sitemap_xml([url])),
        )
        respx.head(url).mock(
            return_value=httpx.Response(
                200, headers={"Last-Modified": "Wed, 01 May 2026 00:00:00 GMT"}
            )
        )
        get_route = respx.get(url)
        store = _RecordingStore(
            last_modified_map={url: datetime(2026, 5, 10, 0, 0, tzinfo=UTC)}
        )

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_index(
                sitemap_url=_SITEMAP_URL,
                fetcher=fetcher,
                embedder=MockEmbeddingClient(),
                store=store,
            )

        assert outcome.skipped_unchanged == 1
        assert outcome.rows_written == 0
        assert outcome.head_checks == 1
        assert get_route.called is False
        assert store.upserted == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetches_when_head_lastmodified_newer(
        self, fetcher_config: PoliteFetcherConfig
    ) -> None:
        url = "https://www.city.fujisawa.kanagawa.jp/page-a"
        respx.get(_SITEMAP_URL).mock(
            return_value=httpx.Response(200, content=_sitemap_xml([url])),
        )
        respx.head(url).mock(
            return_value=httpx.Response(
                200, headers={"Last-Modified": "Wed, 15 May 2026 00:00:00 GMT"}
            )
        )
        respx.get(url).mock(
            return_value=httpx.Response(
                200,
                text="<html><body><main>更新あり</main></body></html>",
                headers={"Last-Modified": "Wed, 15 May 2026 00:00:00 GMT"},
            )
        )
        store = _RecordingStore(
            last_modified_map={url: datetime(2026, 5, 1, 0, 0, tzinfo=UTC)}
        )

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_index(
                sitemap_url=_SITEMAP_URL,
                fetcher=fetcher,
                embedder=MockEmbeddingClient(),
                store=store,
            )

        assert outcome.rows_written == 1
        assert outcome.skipped_unchanged == 0
        assert outcome.head_checks == 1
        assert len(store.upserted) == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetches_when_db_row_exists_but_lastmodified_null(
        self, fetcher_config: PoliteFetcherConfig
    ) -> None:
        """DB に row はあるが last_modified が NULL のときは保守的に GET。"""
        url = "https://www.city.fujisawa.kanagawa.jp/page-a"
        respx.get(_SITEMAP_URL).mock(
            return_value=httpx.Response(200, content=_sitemap_xml([url])),
        )
        head_route = respx.head(url)
        respx.get(url).mock(
            return_value=httpx.Response(
                200,
                text="<html><body><main>本文</main></body></html>",
            )
        )
        store = _RecordingStore(last_modified_map={url: None})

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_index(
                sitemap_url=_SITEMAP_URL,
                fetcher=fetcher,
                embedder=MockEmbeddingClient(),
                store=store,
            )

        assert outcome.rows_written == 1
        assert outcome.head_checks == 0  # NULL → HEAD スキップ
        assert head_route.called is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetches_when_head_returns_no_last_modified(
        self, fetcher_config: PoliteFetcherConfig
    ) -> None:
        """HEAD が Last-Modified を返さない場合は保守的に GET。"""
        url = "https://www.city.fujisawa.kanagawa.jp/page-a"
        respx.get(_SITEMAP_URL).mock(
            return_value=httpx.Response(200, content=_sitemap_xml([url])),
        )
        respx.head(url).mock(return_value=httpx.Response(200))  # no Last-Modified
        respx.get(url).mock(
            return_value=httpx.Response(
                200,
                text="<html><body><main>本文</main></body></html>",
            )
        )
        store = _RecordingStore(
            last_modified_map={url: datetime(2026, 5, 1, 0, 0, tzinfo=UTC)}
        )

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_index(
                sitemap_url=_SITEMAP_URL,
                fetcher=fetcher,
                embedder=MockEmbeddingClient(),
                store=store,
            )

        assert outcome.rows_written == 1
        assert outcome.head_checks == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_falls_back_to_get_when_head_fails(
        self, fetcher_config: PoliteFetcherConfig
    ) -> None:
        """HEAD で 5xx 等が来たら GET に fallback。"""
        url = "https://www.city.fujisawa.kanagawa.jp/page-a"
        respx.get(_SITEMAP_URL).mock(
            return_value=httpx.Response(200, content=_sitemap_xml([url])),
        )
        respx.head(url).mock(return_value=httpx.Response(500))
        respx.get(url).mock(
            return_value=httpx.Response(
                200,
                text="<html><body><main>本文</main></body></html>",
            )
        )
        store = _RecordingStore(
            last_modified_map={url: datetime(2026, 5, 1, 0, 0, tzinfo=UTC)}
        )

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_index(
                sitemap_url=_SITEMAP_URL,
                fetcher=fetcher,
                embedder=MockEmbeddingClient(),
                store=store,
            )

        assert outcome.rows_written == 1
        # HEAD 自体は呼ばれたので head_checks=1
        assert outcome.head_checks == 1


class TestCrawlAndIndexErrorHandling:
    @pytest.mark.asyncio
    @respx.mock
    async def test_skips_url_when_extracted_text_is_empty(
        self, fetcher_config: PoliteFetcherConfig
    ) -> None:
        url = "https://www.city.fujisawa.kanagawa.jp/empty"
        respx.get(_SITEMAP_URL).mock(
            return_value=httpx.Response(200, content=_sitemap_xml([url])),
        )
        respx.get(url).mock(
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
                store=store,
            )

        assert outcome.rows_written == 0
        assert outcome.skipped_empty == 1
        assert store.upserted == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_continues_after_per_url_failure(
        self, fetcher_config: PoliteFetcherConfig
    ) -> None:
        """個別 URL が 4xx 等で fail しても、 他 URL の処理は続行される。"""
        urls = [
            "https://www.city.fujisawa.kanagawa.jp/ok",
            "https://www.city.fujisawa.kanagawa.jp/missing",
        ]
        respx.get(_SITEMAP_URL).mock(
            return_value=httpx.Response(200, content=_sitemap_xml(urls)),
        )
        respx.get(urls[0]).mock(
            return_value=httpx.Response(
                200,
                text="<html><body><main><p>ok page</p></main></body></html>",
            )
        )
        respx.get(urls[1]).mock(return_value=httpx.Response(404))
        store = _RecordingStore()

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_index(
                sitemap_url=_SITEMAP_URL,
                fetcher=fetcher,
                embedder=MockEmbeddingClient(),
                store=store,
            )

        assert outcome.rows_written == 1
        assert outcome.failed_urls == 1
        assert len(store.upserted) == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_dry_run_does_not_call_upsert(
        self, fetcher_config: PoliteFetcherConfig
    ) -> None:
        url = "https://www.city.fujisawa.kanagawa.jp/page-a"
        respx.get(_SITEMAP_URL).mock(
            return_value=httpx.Response(200, content=_sitemap_xml([url])),
        )
        respx.get(url).mock(
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
                store=store,
                dry_run=True,
            )

        # dry-run は store を叩かないが、 parse 結果はカウントする
        assert outcome.rows_written == 1
        assert store.upserted == []


# ─────────────────────────────────────────────────────────────────────
# run_weekly_crawl (Cloud Run Job entrypoint)
# ─────────────────────────────────────────────────────────────────────


class _FakeRunsRepo:
    def __init__(self) -> None:
        self.starts: list[dict[str, Any]] = []
        self.finishes: list[dict[str, Any]] = []
        self.aborts: list[dict[str, Any]] = []

    async def start_run(self, **kwargs: Any) -> None:
        self.starts.append(kwargs)

    async def finish_run(self, **kwargs: Any) -> None:
        self.finishes.append(kwargs)

    async def recent_runs(self, job_name: str, *, limit: int = 5) -> list[Any]:
        return []

    async def abort_stale_running(self, **kwargs: Any) -> int:
        self.aborts.append(kwargs)
        return 0


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
            store=store,
            runs_repo=repo,  # type: ignore[arg-type]
            run_id="weekly_crawl_etl-20260510-0300",
            now=lambda: datetime(2026, 5, 10, 3, 0, tzinfo=UTC),
        )

        assert isinstance(result, EtlRunResult)
        assert result.status == "success"
        assert result.rows_written == 1
        assert len(repo.finishes) == 1
        assert repo.finishes[0]["status"] == "success"
        # runner が abort_stale_running を呼ぶことを確認
        assert len(repo.aborts) == 1


class TestCrawlOutcomeModel:
    def test_frozen(self) -> None:
        outcome = CrawlOutcome(
            rows_written=10,
            skipped_unchanged=5,
            skipped_not_modified=0,
            skipped_empty=0,
            failed_urls=1,
            head_checks=20,
            sitemap_hash="a" * 64,
        )
        with pytest.raises(Exception):
            outcome.rows_written = 99  # type: ignore[misc]
