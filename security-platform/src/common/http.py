"""外部取得用の HTTP クライアント (同期)。5xx と通信エラーは指数バックオフで再試行する。"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

USER_AGENT = "agent-monorepo-security-platform/0.1 (+intel collector)"
RETRIES = 4


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        timeout=settings.http_timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
        transport=transport,
    )


def with_retry[T](fn: Callable[[], T], *, what: str, sleep: Callable[[float], None] = time.sleep) -> T:
    for attempt in range(RETRIES):
        try:
            return fn()
        except httpx.HTTPStatusError as e:
            if e.response.status_code < 500 or attempt == RETRIES - 1:
                raise
            logger.warning("%s: HTTP %s, retrying", what, e.response.status_code)
        except (httpx.TransportError, httpx.DecodingError):
            if attempt == RETRIES - 1:
                raise
            logger.warning("%s: transport error, retrying", what)
        sleep(2.0 ** (attempt + 1))
    raise RuntimeError("unreachable")
