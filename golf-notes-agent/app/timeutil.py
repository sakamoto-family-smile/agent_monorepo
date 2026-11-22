"""時刻の表し方をそろえる。

DB には UTC の ``YYYY-MM-DDTHH:MM:SSZ`` で保存する (文字列の大小比較がそのまま時刻の比較になる)。
日付 (セッションの日付など) は設定のタイムゾーン (既定 Asia/Tokyo) で決める。
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

Clock = Callable[[], datetime]


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("naive datetime")
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def local_date(dt: datetime, tz: ZoneInfo) -> date:
    return dt.astimezone(tz).date()


def from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, UTC)


def month_start(dt: datetime, tz: ZoneInfo) -> datetime:
    local = dt.astimezone(tz)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def add_seconds(dt: datetime, seconds: float) -> datetime:
    return dt + timedelta(seconds=seconds)
