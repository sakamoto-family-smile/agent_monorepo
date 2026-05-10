"""weekly_crawl_etl: 藤沢市 sitemap.xml を起点に各 URL を polite crawl する ETL Job。

実行頻度 (proposal 0003 §4.5.4): 毎週日曜 03:00 JST、Cloud Run Job として配備。

処理フロー:
  [1] sitemap.xml 取得 (PoliteFetcher)
  [2] parse_sitemap → list[SitemapEntry] (~1,100 URL)
  [3] 各 URL を polite fetch (1 URL/3s ≈ 1 時間)
       - 304 Not Modified → upsert skip
       - 4xx/5xx → 当該 URL のみ skip、Job 全体は続行
  [4] HTML から `<main>` 本文抽出 (`extract_main_text`)
  [5] Vertex (or Mock) で embedding
  [6] PgvectorStore.upsert_page で Cloud SQL に upsert

書き込み先テーブル: `pages` (HTML 本文 + embedding)
利用先: LINE bot (proposal 0004) RAG。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

import httpx
from pydantic import BaseModel, ConfigDict

from fujisawa_platform.crawler import (
    FetchResult,
    NotModified,
    PoliteFetcher,
    PoliteFetcherConfig,
    parse_sitemap,
)
from fujisawa_platform.etl._html import extract_main_text, extract_title
from fujisawa_platform.etl._runner import EtlRunResult, run_etl_job
from fujisawa_platform.knowledge_base import EmbeddingClient
from fujisawa_platform.knowledge_base.store import PageDocument

if TYPE_CHECKING:  # pragma: no cover
    from fujisawa_platform.etl._repos.etl_runs import EtlRunsRepo


class _StoreLike(Protocol):
    """`PgvectorStore` / `InMemoryStore` のうち本 ETL が必要とする最小 API。"""

    async def upsert_page(self, page: PageDocument) -> None: ...


class CrawlOutcome(BaseModel):
    """`crawl_and_index` の戻り値。

    `run_weekly_crawl` ラッパーがこの値を `EtlRunResult` に変換する。
    """

    model_config = ConfigDict(frozen=True)

    rows_written: int = 0
    skipped_not_modified: int = 0
    skipped_empty: int = 0
    failed_urls: int = 0
    sitemap_hash: str | None = None


async def crawl_and_index(
    *,
    sitemap_url: str,
    fetcher: PoliteFetcher,
    embedder: EmbeddingClient,
    store: _StoreLike,
    if_modified_since: datetime | None = None,
    now: Callable[[], datetime] | None = None,
    dry_run: bool = False,
) -> CrawlOutcome:
    """sitemap → URL ごと fetch → embed → upsert を 1 回分実行する。

    Args:
        sitemap_url: 起点 sitemap.xml の URL。
        fetcher: PoliteFetcher (consumer 側で `async with` 済のもの)。
        embedder: EmbeddingClient 実装 (本番は Vertex、テストは Mock)。
        store: `upsert_page` を持つ object (PgvectorStore / InMemoryStore)。
        if_modified_since: 個別 URL fetch の If-Modified-Since 値 (任意)。
        now: 任意。fetched_at の差し替え (テスト用)。
        dry_run: True の場合、parse は行うが store には書き込まない。

    Returns:
        CrawlOutcome (rows_written, skipped カウント, sitemap_hash)。
    """
    _now = now or _utcnow

    sitemap_result = await fetcher.fetch(sitemap_url)
    if isinstance(sitemap_result, NotModified):
        return CrawlOutcome(sitemap_hash=None)
    sitemap_bytes = sitemap_result.text.encode("utf-8")
    sitemap_hash = _sha256(sitemap_bytes)
    entries = parse_sitemap(sitemap_bytes)

    rows = 0
    skipped_304 = 0
    skipped_empty = 0
    failed = 0

    for entry in entries:
        url_str = str(entry.url)
        try:
            page_result = await fetcher.fetch(url_str, if_modified_since=if_modified_since)
        except (httpx.HTTPStatusError, httpx.HTTPError):
            failed += 1
            continue

        if isinstance(page_result, NotModified):
            skipped_304 += 1
            continue

        assert isinstance(page_result, FetchResult)
        text = extract_main_text(page_result.text)
        if not text:
            skipped_empty += 1
            continue

        page = PageDocument(
            page_id=_sha256(url_str.encode("utf-8")),
            url=url_str,
            title=extract_title(page_result.text),
            content=text,
            embedding=embedder.embed(text),
            fetched_at=_now(),
            last_modified=page_result.last_modified,
        )
        if not dry_run:
            await store.upsert_page(page)
        rows += 1

    return CrawlOutcome(
        rows_written=rows,
        skipped_not_modified=skipped_304,
        skipped_empty=skipped_empty,
        failed_urls=failed,
        sitemap_hash=sitemap_hash,
    )


async def run_weekly_crawl(
    *,
    sitemap_url: str,
    fetcher_config: PoliteFetcherConfig,
    embedder: EmbeddingClient,
    store: _StoreLike,
    runs_repo: EtlRunsRepo,
    run_id: str,
    if_modified_since: datetime | None = None,
    now: Callable[[], datetime] | None = None,
    dry_run: bool = False,
) -> EtlRunResult:
    """Cloud Run Job のエントリポイント。

    `run_etl_job` ラッパーで `etl_runs` への記録 / fail-fast / skip を統合。
    """

    async def _job() -> EtlRunResult:
        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_index(
                sitemap_url=sitemap_url,
                fetcher=fetcher,
                embedder=embedder,
                store=store,
                if_modified_since=if_modified_since,
                now=now,
                dry_run=dry_run,
            )
        return EtlRunResult(
            rows_written=outcome.rows_written,
            source_url=sitemap_url,
            source_hash=outcome.sitemap_hash,
            status="success",
        )

    return await run_etl_job(
        job_name="weekly_crawl_etl",
        run_id=run_id,
        repo=runs_repo,
        fn=_job,
        now=now,
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = ["CrawlOutcome", "crawl_and_index", "run_weekly_crawl"]


# `etl/__init__.py` の re-export はモジュール末尾の方が import 順を整えやすい
# ため、ここで意図的に追加 export はしない (necessary symbols は `etl/__init__.py`
# 側で逐次追加する)。
