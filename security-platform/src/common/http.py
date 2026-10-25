"""外部取得用の HTTP クライアント (同期)。5xx・429 と通信エラーは指数バックオフで再試行する。

429 / 503 に Retry-After (秒) が付いていればそれに従う (上限 MAX_RETRY_AFTER 秒)。
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

USER_AGENT = "agent-monorepo-security-platform/0.1 (+intel collector)"
RETRIES = 4
MAX_RETRY_AFTER = 120.0


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After", "")
    try:
        return min(max(float(value), 0.0), MAX_RETRY_AFTER)
    except ValueError:
        return None


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        timeout=settings.http_timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
        transport=transport,
    )


def with_retry[T](fn: Callable[[], T], *, what: str, sleep: Callable[[float], None] = time.sleep) -> T:
    for attempt in range(RETRIES):
        wait = 2.0 ** (attempt + 1)
        try:
            return fn()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if (status < 500 and status != 429) or attempt == RETRIES - 1:
                raise
            wait = _retry_after(e.response) or wait
            logger.warning("%s: HTTP %s, retrying in %.0fs", what, status, wait)
        except (httpx.TransportError, httpx.DecodingError):
            if attempt == RETRIES - 1:
                raise
            logger.warning("%s: transport error, retrying", what)
        sleep(wait)
    raise RuntimeError("unreachable")
