"""crawler module: 藤沢市 HP / RSS / Wayback の polite な取得層。"""

from fujisawa_platform.crawler.polite_fetcher import (
    FetchResult,
    NotModified,
    PoliteFetcher,
    PoliteFetcherConfig,
)
from fujisawa_platform.crawler.sitemap_loader import (
    SitemapEntry,
    SitemapParseError,
    parse_sitemap,
)

__all__ = [
    "FetchResult",
    "NotModified",
    "PoliteFetcher",
    "PoliteFetcherConfig",
    "SitemapEntry",
    "SitemapParseError",
    "parse_sitemap",
]
