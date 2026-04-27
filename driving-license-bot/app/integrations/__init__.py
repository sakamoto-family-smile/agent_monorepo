"""外部 HTTP 統合（e-Gov、Wikimedia、警察庁、その他）。

セキュリティ要件:
- 全ての外部 HTTP 呼び出しは security-platform の MCP Proxy 配下で
  observability + DLP + rate limit を効かせる方針（DESIGN.md §15.2）。
- そのため `proxied_http_client.py` 経由で `httpx.AsyncClient` を作る。
"""

from app.integrations.egov_law_client import (
    EgovLawClient,
    EgovLawError,
    LawArticleSnapshot,
)
from app.integrations.proxied_http_client import build_proxied_async_client

__all__ = [
    "EgovLawClient",
    "EgovLawError",
    "LawArticleSnapshot",
    "build_proxied_async_client",
]
