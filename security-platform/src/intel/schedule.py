"""情報源ごとの取得間隔。intel の常駐と、notify の取得停止の監視が同じ値を使う。"""
from __future__ import annotations

from datetime import timedelta

from ..config import settings

# 最終成功からこの倍数だけ経っても成功していなければ「止まっている」とみなす
STALE_FACTOR = 3


def schedule() -> dict[str, timedelta]:
    return {
        "osv": timedelta(hours=1),
        "kev": timedelta(hours=1),
        "epss": timedelta(days=1),
        "osv_full": timedelta(days=settings.osv_full_refresh_days),
    }
