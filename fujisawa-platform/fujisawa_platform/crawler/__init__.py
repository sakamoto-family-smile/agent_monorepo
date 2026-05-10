"""crawler module: 藤沢市 HP / RSS / Wayback の polite な取得層。"""

from fujisawa_platform.crawler.polite_fetcher import (
    FetchResult,
    NotModified,
    PoliteFetcher,
    PoliteFetcherConfig,
)
from fujisawa_platform.crawler.rss_poller import (
    RssEntry,
    RssParseError,
    parse_feed,
)
from fujisawa_platform.crawler.sitemap_loader import (
    SitemapEntry,
    SitemapParseError,
    parse_sitemap,
)
from fujisawa_platform.crawler.wayback import (
    WaybackClient,
    WaybackConfig,
    WaybackError,
    WaybackSnapshot,
    build_archive_url,
)

__all__ = [
    "FetchResult",
    "NotModified",
    "PoliteFetcher",
    "PoliteFetcherConfig",
    "RssEntry",
    "RssParseError",
    "SitemapEntry",
    "SitemapParseError",
    "WaybackClient",
    "WaybackConfig",
    "WaybackError",
    "WaybackSnapshot",
    "build_archive_url",
    "parse_feed",
    "parse_sitemap",
]
