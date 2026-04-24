"""arXiv 公式 API からの論文収集。

`arxiv` パッケージを使用。arXiv 公式ガイドラインに従い、1 リクエスト / 3 秒の
rate limit を守る (ソース設定から注入)。同期呼び出しを `asyncio.to_thread` で
ラップして event loop をブロックしない。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from models import RawArticle
from services.source_config import ArxivSourceConfig
from services.url_normalizer import article_id, normalize_url

logger = logging.getLogger(__name__)


def _build_query(categories: tuple[str, ...]) -> str:
    # OR 連結で複数カテゴリを対象に
    return " OR ".join(f"cat:{c}" for c in categories)


def _to_raw_article(result: Any, source_name: str, fetched_at: datetime) -> RawArticle | None:
    """arxiv.Result → RawArticle。"""
    url = getattr(result, "entry_id", "") or ""
    if not url:
        return None
    title = (getattr(result, "title", "") or "").strip()
    if not title:
        return None
    content = (getattr(result, "summary", "") or "").strip()
    authors = getattr(result, "authors", []) or []
    author_names = ", ".join(getattr(a, "name", str(a)) for a in authors[:5])
    published = getattr(result, "published", None)
    if published is not None and isinstance(published, datetime) and published.tzinfo is None:
        published = published.replace(tzinfo=UTC)

    primary_cat = getattr(result, "primary_category", None)
    pdf_url = getattr(result, "pdf_url", None)

    normalized = normalize_url(url)
    return RawArticle(
        article_id=article_id(normalized),
        source_type="arxiv",
        source_name=source_name,
        url=url,
        url_normalized=normalized,
        title=title,
        content=content,
        content_preview=content[:500] + ("…" if len(content) > 500 else ""),
        author=author_names or None,
        published_at=published,
        fetched_at=fetched_at,
        arxiv_primary_category=primary_cat,
        arxiv_pdf_url=pdf_url,
    )


def _fetch_sync(source: ArxivSourceConfig) -> list[Any]:
    """arxiv パッケージを同期で叩いて Result リストを取得。

    遅延 import にしておく (lint で本体 import 必須ではない)。
    """
    import arxiv  # noqa: PLC0415

    client = arxiv.Client(
        page_size=min(source.max_results, 100),
        delay_seconds=source.rate_limit_seconds,
        num_retries=3,
    )
    search = arxiv.Search(
        query=_build_query(source.categories),
        max_results=source.max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )
    return list(client.results(search))


async def fetch_source(source: ArxivSourceConfig) -> list[RawArticle]:
    """arXiv 1 ソースから取得。失敗時は空リスト。"""
    fetched_at = datetime.now(UTC)
    try:
        raw_results = await asyncio.to_thread(_fetch_sync, source)
    except Exception as exc:
        logger.warning("arxiv fetch failed source=%s error=%s", source.name, exc)
        return []

    articles: list[RawArticle] = []
    for r in raw_results:
        try:
            art = _to_raw_article(r, source.name, fetched_at)
        except Exception as exc:
            logger.warning("arxiv entry parse failed: %s", exc)
            continue
        if art is not None:
            articles.append(art)

    logger.info(
        "arxiv fetched source=%s categories=%s entries=%d",
        source.name,
        ",".join(source.categories),
        len(articles),
    )
    return articles


async def fetch_all(sources: list[ArxivSourceConfig]) -> list[RawArticle]:
    """複数 arXiv ソース (現状は通常 1 つ) を並列で取得。"""
    results = await asyncio.gather(
        *[fetch_source(s) for s in sources],
        return_exceptions=True,
    )
    articles: list[RawArticle] = []
    for r in results:
        if isinstance(r, Exception):
            logger.error("arxiv unexpected error: %s", r)
            continue
        articles.extend(r)
    return articles
