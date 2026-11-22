"""Healthchecks.io 互換の ping (PROPOSAL-0013 §5.1)。

security-platform の `src/common/healthcheck.py` と同じ形: ジョブごとに `<base>/stock-<job>`
(失敗は末尾に `/fail`) へ GET し、`?create=1` で check を自動作成させる。
Ping key が URL に入るので、リクエスト URL をログに出さない (httpx の INFO ログを止める)。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import httpx

SLUG_PREFIX = "stock-"
PING_TIMEOUT_SECONDS = 10.0

logger = logging.getLogger(__name__)

Pinger = Callable[[str, bool], Awaitable[None]]


def make_pinger(base: str, *, client: httpx.AsyncClient | None = None) -> Pinger | None:
    """ping 関数を返す。base が空なら None (ping しない)。"""
    if not base:
        return None
    logging.getLogger("httpx").setLevel(logging.WARNING)
    base = base.rstrip("/")

    async def ping(job: str, ok: bool) -> None:
        url = f"{base}/{SLUG_PREFIX}{job}" + ("" if ok else "/fail")
        try:
            if client is not None:
                await client.get(url, params={"create": 1}, timeout=PING_TIMEOUT_SECONDS)
                return
            async with httpx.AsyncClient() as c:
                await c.get(url, params={"create": 1}, timeout=PING_TIMEOUT_SECONDS)
        except httpx.HTTPError as e:
            # URL (Ping key 入り) は出さず、ジョブ名と例外の種類だけ残す
            logger.warning("healthcheck ping failed (job=%s, %s)", job, type(e).__name__)

    return ping


__all__ = ["SLUG_PREFIX", "Pinger", "make_pinger"]
