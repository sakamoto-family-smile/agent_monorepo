"""`on_call` コールバック呼び出しヘルパ。"""

from __future__ import annotations

import logging
import time
from typing import Any

from .types import OnCallCallback

logger = logging.getLogger(__name__)


def safe_emit(
    callback: OnCallCallback | None,
    *,
    provider: str,
    model: str,
    resp: Any,
    started: float,
    error: Exception | None,
) -> None:
    """`on_call` コールバックを安全に呼ぶ (例外は握り潰す)。

    observability の失敗で本処理を止めたくないため、ここで try/except する。
    """
    if callback is None:
        return
    try:
        callback(
            {
                "provider": provider,
                "model": model,
                "resp": resp,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "error": error,
            }
        )
    except Exception:
        logger.exception("on_call callback raised; ignoring to protect caller")
