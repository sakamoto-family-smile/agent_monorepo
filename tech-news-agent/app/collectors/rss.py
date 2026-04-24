"""RSS / Atom フィード収集。

- `feedparser` で parse、ソース毎に try/except して 1 ソースの失敗が
  他ソースに影響しないようにする
- HTTP 取得は `httpx.AsyncClient` (同期 feedparser に生データを渡す形)、
  User-Agent ヘッダを明示してリモート側の access log 解析を助ける
- tenacity で一時的なネットワークエラーに backoff (5 回、1→2→4→8→16 秒)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import feedparser
import httpx
from models import RawArticle
from services.source_config import RssSourceConfig
from services.url_normalizer import article_id, normalize_url
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "tech-news-agent/0.1 (+https://github.com/sakamoto-family-smile/agent_monorepo)"
)
DEFAULT_TIMEOUT = 20.0


HttpFetch = Callable[[str], Awaitable[bytes]]
"""URL → bytes の抽象 (テスト差替え用)。"""


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    reraise=True,
)
async def _default_http_fetch(url: str) -> bytes:
    async with httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT,
        headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, text/xml"},
        follow_redirects=True,
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


def _content_preview(text: str, limit: int = 500) -> str:
    clean = (text or "").strip()
    if len(clean) <= limit:
        return clean
    return clean[:limit] + "…"


def _parse_entry(source: RssSourceConfig, entry: dict, fetched_at: datetime) -> RawArticle | None:
    url = entry.get("link") or ""
    if not url:
        return None
    title = (entry.get("title") or "").strip()
    if not title:
        return None
    content = (
        entry.get("summary")
        or (entry.get("content") or [{}])[0].get("value")
        or ""
    )
    published = None
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            published = datetime(*parsed[:6], tzinfo=UTC)
        except (TypeError, ValueError):
            published = None

    normalized = normalize_url(url)
    return RawArticle(
        article_id=article_id(normalized),
        source_type="rss",
        source_name=source.name,
        url=url,
        url_normalized=normalized,
        title=title,
        content=content,
        content_preview=_content_preview(content),
        author=(entry.get("author") or None),
        published_at=published,
        fetched_at=fetched_at,
    )


async def fetch_source(
    source: RssSourceConfig,
    *,
    http_fetch: HttpFetch | None = None,
) -> list[RawArticle]:
    """1 ソースから記事取得。失敗時は [] を返し呼び出し元には例外を出さない。

    `http_fetch=None` の場合はモジュール属性 `_default_http_fetch` を **遅延解決** し、
    monkeypatch による差替えが確実に効くようにする。
    """
    fetcher = http_fetch or _default_http_fetch
    fetched_at = datetime.now(UTC)
    try:
        body = await fetcher(source.url)
    except Exception as exc:
        logger.warning("rss fetch failed source=%s url=%s error=%s", source.name, source.url, exc)
        return []

    # feedparser は同期 API。CPU 軽量なので event loop に直接流す
    feed = feedparser.parse(body)
    if feed.bozo and not feed.entries:
        logger.warning(
            "rss parse had no entries source=%s bozo=%s", source.name, feed.bozo_exception
        )
        return []

    articles: list[RawArticle] = []
    for entry in feed.entries:
        try:
            art = _parse_entry(source, entry, fetched_at)
        except Exception as exc:
            logger.warning("rss entry parse failed source=%s error=%s", source.name, exc)
            continue
        if art is not None:
            articles.append(art)

    logger.info("rss fetched source=%s entries=%d", source.name, len(articles))
    return articles


async def fetch_all(
    sources: list[RssSourceConfig],
    *,
    http_fetch: HttpFetch | None = None,
) -> list[RawArticle]:
    """複数ソースを並列で取得。`http_fetch=None` でデフォルト (monkeypatch 可能)。"""
    results = await asyncio.gather(
        *[fetch_source(s, http_fetch=http_fetch) for s in sources],
        return_exceptions=True,
    )
    articles: list[RawArticle] = []
    for r in results:
        if isinstance(r, Exception):
            logger.error("rss unexpected error: %s", r)
            continue
        articles.extend(r)
    return articles
