"""security-platform の egress proxy を経由する httpx.AsyncClient ファクトリ。

設計（DESIGN.md §15.2 / INTEGRATIONS.md §15.2.3）:
- 外部 HTTP 呼び出しは security-platform/MCP Proxy 配下で observability +
  DLP + rate limit を効かせる
- 環境変数 `SECURITY_HTTP_PROXY_URL` が設定されている場合のみ proxy 経由
- 未設定なら直接外向き（local 開発・CI 用フォールバック）

Phase 2-F: 単純な `httpx` ラッパ。Phase 4 で MCP Proxy が HTTP 中継機能を
正式サポートしたタイミングで proxy ヘッダ仕様を確定させる。
"""

from __future__ import annotations

import logging

import httpx

import app.config

logger = logging.getLogger(__name__)


# 既定 timeout（seconds）。e-Gov API は遅いことがあるので長め。
DEFAULT_TIMEOUT_SECONDS = 30.0


def build_proxied_async_client(
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    extra_headers: dict[str, str] | None = None,
) -> httpx.AsyncClient:
    """proxy 経由 / 直接 を env で切替する httpx.AsyncClient を返す。

    呼び出し側は `async with build_proxied_async_client() as client:` で利用する。
    """
    settings = app.config.settings
    proxy_url = (settings.security_http_proxy_url or "").strip()
    headers: dict[str, str] = {
        "User-Agent": (
            f"driving-license-bot/{settings.service_version} "
            f"(+{settings.service_name})"
        ),
    }
    if extra_headers:
        headers.update(extra_headers)

    if proxy_url:
        logger.debug("building proxied http client via %s", proxy_url)
        return httpx.AsyncClient(
            proxy=proxy_url,
            timeout=timeout,
            headers=headers,
            follow_redirects=True,
        )
    logger.debug("building direct http client (no proxy configured)")
    return httpx.AsyncClient(
        timeout=timeout,
        headers=headers,
        follow_redirects=True,
    )


__all__ = ["DEFAULT_TIMEOUT_SECONDS", "build_proxied_async_client"]
