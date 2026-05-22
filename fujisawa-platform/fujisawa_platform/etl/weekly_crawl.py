"""weekly_crawl_etl: 藤沢市 sitemap.xml を起点に差分 crawl する ETL Job。

実行頻度 (proposal 0003 §4.5.4 v2): 毎週日曜 03:00 JST、 Cloud Run Job として配備。

差分 crawl フロー (2026-05-21 改訂):
  [1] sitemap.xml 取得 (PoliteFetcher.fetch, GET)
  [2] parse_sitemap → list[SitemapEntry] (~7,900 URL @ 2026-05)
  [3] DB から既存 URL の last_modified を一括取得 (`store.get_last_modified_map`)
  [4] 各 URL について以下を判定:
       - DB に無い URL: 「新規」 → GET 対象
       - DB に有り、 last_modified 未設定: 「不明」 → GET 対象 (保守的)
       - DB に有り、 last_modified 有り → HEAD で現サーバー値を取得し比較
           - HEAD Last-Modified > DB last_modified → GET 対象 (更新あり)
           - それ以外 → 「skip_unchanged」 → GET スキップ
  [5] GET 対象 URL を polite fetch
  [6] HTML から `<main>` 本文抽出
  [7] Vertex (or Mock) で embedding
  [8] PgvectorStore.upsert_page で Cloud SQL に upsert

書き込み先テーブル: `pages`
利用先: LINE bot (proposal 0004) RAG。

差分 crawl の効果 (2026-05 計測):
- sitemap 7,906 URL × GET 3 秒/URL = 6.6 時間 (旧方式は task timeout 5400s で
  全件完走不可)
- 新方式: HEAD 7906 × 0.5s + GET <数百> × 3s ≒ 1〜1.5 時間 (定常運用時)
- 初回 / 大幅更新時は HEAD スキップ + 全件 GET、 task timeout 8 時間で吸収

設計参考: `docs/PROPOSALS/notes/fujisawa-info-bot-follow-up-2026-05-21.md`
"""

from __future__ import annotations

import hashlib
import logging
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
from fujisawa_platform.etl._category_classifier import classify_category
from fujisawa_platform.etl._html import extract_main_text, extract_title
from fujisawa_platform.etl._runner import EtlRunResult, run_etl_job
from fujisawa_platform.knowledge_base import EmbeddingClient
from fujisawa_platform.knowledge_base.store import PageDocument

if TYPE_CHECKING:  # pragma: no cover
    from fujisawa_platform.etl._repos.etl_runs import EtlRunsRepo

logger = logging.getLogger(__name__)


class _StoreLike(Protocol):
    """`PgvectorStore` / `InMemoryStore` のうち本 ETL が必要とする最小 API。"""

    async def upsert_page(self, page: PageDocument) -> None: ...

    async def get_last_modified_map(
        self, urls: list[str]
    ) -> dict[str, datetime | None]: ...


class CrawlOutcome(BaseModel):
    """`crawl_and_index` の戻り値。

    `run_weekly_crawl` ラッパーがこの値を `EtlRunResult` に変換する。
    """

    model_config = ConfigDict(frozen=True)

    rows_written: int = 0
    skipped_unchanged: int = 0  # HEAD 比較で skip した URL (新方式の主要メトリクス)
    skipped_not_modified: int = 0  # GET の 304 で skip した URL (新方式では稀)
    skipped_empty: int = 0
    failed_urls: int = 0
    head_checks: int = 0  # HEAD を打った URL 数 (HEAD cost 計測用)
    sitemap_hash: str | None = None


async def crawl_and_index(
    *,
    sitemap_url: str,
    fetcher: PoliteFetcher,
    embedder: EmbeddingClient,
    store: _StoreLike,
    now: Callable[[], datetime] | None = None,
    dry_run: bool = False,
) -> CrawlOutcome:
    """sitemap → 差分判定 → GET → embed → upsert を 1 回分実行する。

    Args:
        sitemap_url: 起点 sitemap.xml の URL。
        fetcher: PoliteFetcher (consumer 側で `async with` 済のもの)。
        embedder: EmbeddingClient 実装 (本番は Vertex、 テストは Mock)。
        store: `upsert_page` + `get_last_modified_map` を持つ object。
        now: 任意。 fetched_at の差し替え (テスト用)。
        dry_run: True の場合、 parse / HEAD は行うが store には書き込まない。

    Returns:
        CrawlOutcome (rows_written, skipped カウント, sitemap_hash, head_checks)。
    """
    _now = now or _utcnow

    sitemap_result = await fetcher.fetch(sitemap_url)
    if isinstance(sitemap_result, NotModified):
        return CrawlOutcome(sitemap_hash=None)
    sitemap_bytes = sitemap_result.text.encode("utf-8")
    sitemap_hash = _sha256(sitemap_bytes)
    entries = parse_sitemap(sitemap_bytes)
    sitemap_urls = [str(entry.url) for entry in entries]

    # DB から既知 URL の last_modified を一括取得
    db_last_modified = await store.get_last_modified_map(sitemap_urls)

    rows = 0
    skipped_unchanged = 0
    skipped_304 = 0
    skipped_empty = 0
    failed = 0
    head_checks = 0

    for entry in entries:
        url_str = str(entry.url)
        db_lm = db_last_modified.get(url_str)
        needs_get, head_used = await _decide_needs_get(
            url_str=url_str,
            db_last_modified=db_lm,
            db_has_row=url_str in db_last_modified,
            fetcher=fetcher,
        )
        if head_used:
            head_checks += 1
        if not needs_get:
            skipped_unchanged += 1
            continue

        try:
            page_result = await fetcher.fetch(url_str)
        except (httpx.HTTPStatusError, httpx.HTTPError):
            failed += 1
            continue

        if isinstance(page_result, NotModified):
            # 差分 crawl では If-Modified-Since を送らないため通常は起きないが、
            # 念のためカウントだけはしておく。
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
            category=classify_category(url_str),
            fetched_at=_now(),
            last_modified=page_result.last_modified,
        )
        if not dry_run:
            await store.upsert_page(page)
        rows += 1

    return CrawlOutcome(
        rows_written=rows,
        skipped_unchanged=skipped_unchanged,
        skipped_not_modified=skipped_304,
        skipped_empty=skipped_empty,
        failed_urls=failed,
        head_checks=head_checks,
        sitemap_hash=sitemap_hash,
    )


async def _decide_needs_get(
    *,
    url_str: str,
    db_last_modified: datetime | None,
    db_has_row: bool,
    fetcher: PoliteFetcher,
) -> tuple[bool, bool]:
    """1 URL について GET が必要か判定する。 (needs_get, head_used) を返す。

    - DB に row が無い → GET 必要 (HEAD 不要)
    - DB に row 有り + last_modified None → 保守的に GET 必要 (HEAD 不要)
    - DB に row 有り + last_modified 有り → HEAD 発行して比較
        - HEAD 失敗 (4xx/5xx) → 保守的に GET 必要 (=旧データで応答するよりは新規取得を試す)
        - HEAD 成功 + サーバー側 last_modified > DB 値 → GET 必要
        - それ以外 → GET 不要
    """
    if not db_has_row:
        return True, False
    if db_last_modified is None:
        return True, False
    try:
        head = await fetcher.head(url_str)
    except (httpx.HTTPStatusError, httpx.HTTPError):
        logger.debug("HEAD failed for %s, falling back to GET", url_str)
        return True, True
    if head.last_modified is None:
        # サーバーが Last-Modified を返さない → 比較不能なので保守的に GET
        return True, True
    if head.last_modified > db_last_modified:
        return True, True
    return False, True


async def run_weekly_crawl(
    *,
    sitemap_url: str,
    fetcher_config: PoliteFetcherConfig,
    embedder: EmbeddingClient,
    store: _StoreLike,
    runs_repo: EtlRunsRepo,
    run_id: str,
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
