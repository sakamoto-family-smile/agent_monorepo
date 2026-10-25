"""ジョブ結果の死活監視 ping (Healthchecks.io 互換)。

``HEALTHCHECK_PING_BASE`` (例: ``https://hc-ping.com/<ping-key>``) を設定すると、ジョブの
成功で ``<base>/<slug>``、失敗で ``<base>/<slug>/fail`` を叩く。slug は ``sec-<job>``。
ping が途絶えたら (Mac のスリープ・Docker Desktop の停止など) 監視側から通知が来る。
"""
from __future__ import annotations

from collections.abc import Callable

import httpx

SLUG_PREFIX = "sec-"


def make_pinger(client: httpx.Client, base: str) -> Callable[[str, bool], None] | None:
    if not base:
        return None
    base = base.rstrip("/")

    def ping(job: str, ok: bool) -> None:
        url = f"{base}/{SLUG_PREFIX}{job}" + ("" if ok else "/fail")
        client.get(url, params={"create": 1}, timeout=10.0)

    return ping
