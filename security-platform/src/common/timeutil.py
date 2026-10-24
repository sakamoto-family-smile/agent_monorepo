"""時刻の扱い。DB には UTC の ISO8601 文字列で保存する。"""
from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_iso() -> str:
    return to_iso(utc_now())


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_iso(value: str) -> datetime:
    """OSV の ``2026-10-23T22:45:03.452878321Z`` のようなナノ秒表記も受け付ける。"""
    v = value.strip().replace("Z", "+00:00")
    if "." in v:
        head, rest = v.split(".", 1)
        frac, sep, tz = rest.partition("+") if "+" in rest else rest.partition("-")
        v = f"{head}.{frac[:6]}{sep}{tz}" if sep else f"{head}.{frac[:6]}"
    dt = datetime.fromisoformat(v)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
