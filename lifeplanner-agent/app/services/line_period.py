"""LINE コマンドの期間引数パース (PR 2)。

`/summary [今月|先月|今年|YYYY-MM YYYY-MM]` のような引数を解析して
`(start: date, end: date, label: str)` を返す純関数群。

設計判断:
  - 「今月」「先月」「今年」のキーワードは日本語固定。半角/全角 OK。
  - JST 前提 (家計データは日本居住者向け)。
  - 不正な入力は ValueError を投げる (handler 側で usage を返す)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

_YYYY_MM_RE = re.compile(r"^(\d{4})-(\d{2})$")
_YYYY_MM_DD_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

# 日本語のキーワード (lower されない、半角に正規化はしない)
_THIS_MONTH = frozenset({"今月", "this_month", "this-month"})
_LAST_MONTH = frozenset({"先月", "last_month", "last-month"})
_THIS_YEAR = frozenset({"今年", "this_year", "this-year"})


@dataclass(frozen=True)
class PeriodRange:
    """期間 (両端 inclusive、JST 日付)。"""

    start: date
    end: date
    label: str  # 表示用 (例: "2025/10", "2025/10〜2025/11", "2025/01〜2025/10")


def _last_day_of_month(year: int, month: int) -> date:
    """指定 (year, month) の最終日。"""
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def _parse_yyyy_mm(s: str) -> date:
    m = _YYYY_MM_RE.match(s)
    if not m:
        raise ValueError(f"日付形式が不正 (YYYY-MM): {s!r}")
    year, month = int(m.group(1)), int(m.group(2))
    if not (1 <= month <= 12):
        raise ValueError(f"月が不正: {s!r}")
    return date(year, month, 1)


def parse_summary_period(args: list[str], *, today: date | None = None) -> PeriodRange:
    """`/summary` の引数を期間に変換。

    args:
      [] → 今月
      ["今月"] → 今月
      ["先月"] → 先月
      ["今年"] → 1/1 〜 today
      ["YYYY-MM", "YYYY-MM"] → 任意月範囲
    """
    today = today or date.today()
    if not args:
        return _this_month(today)

    if len(args) == 1:
        token = args[0]
        if token in _THIS_MONTH:
            return _this_month(today)
        if token in _LAST_MONTH:
            return _last_month(today)
        if token in _THIS_YEAR:
            return _this_year(today)
        # 1 引数で YYYY-MM 単独 → その月のサマリ
        if _YYYY_MM_RE.match(token):
            d = _parse_yyyy_mm(token)
            return PeriodRange(
                start=d,
                end=_last_day_of_month(d.year, d.month),
                label=f"{d.year}/{d.month:02d}",
            )
        raise ValueError(
            f"期間指定が不正: {token!r}。例: 今月 / 先月 / 今年 / 2025-10 / 2025-04 2025-09"
        )

    if len(args) == 2:
        start = _parse_yyyy_mm(args[0])
        end_first = _parse_yyyy_mm(args[1])
        end = _last_day_of_month(end_first.year, end_first.month)
        if end < start:
            raise ValueError("終了月が開始月より前です")
        return PeriodRange(
            start=start,
            end=end,
            label=f"{start.year}/{start.month:02d}〜{end_first.year}/{end_first.month:02d}",
        )

    raise ValueError(
        "期間指定の引数が多すぎます。例: 今月 / 先月 / 今年 / YYYY-MM YYYY-MM"
    )


def _this_month(today: date) -> PeriodRange:
    start = today.replace(day=1)
    end = _last_day_of_month(today.year, today.month)
    return PeriodRange(start=start, end=end, label=f"{today.year}/{today.month:02d}")


def _last_month(today: date) -> PeriodRange:
    if today.month == 1:
        year, month = today.year - 1, 12
    else:
        year, month = today.year, today.month - 1
    return PeriodRange(
        start=date(year, month, 1),
        end=_last_day_of_month(year, month),
        label=f"{year}/{month:02d}",
    )


def _this_year(today: date) -> PeriodRange:
    return PeriodRange(
        start=date(today.year, 1, 1),
        end=today,
        label=f"{today.year}/01〜{today.year}/{today.month:02d}",
    )


def parse_month_arg(token: str | None, *, today: date | None = None) -> tuple[date, str]:
    """`/anomalies [YYYY-MM]` 用。token=None なら今月。

    戻り値: (target_month_first_day, label)
    """
    today = today or date.today()
    if token is None:
        d = today.replace(day=1)
        return d, f"{d.year}/{d.month:02d}"
    if token in _THIS_MONTH:
        d = today.replace(day=1)
        return d, f"{d.year}/{d.month:02d}"
    if token in _LAST_MONTH:
        d = _last_month(today).start
        return d, f"{d.year}/{d.month:02d}"
    d = _parse_yyyy_mm(token)
    return d, f"{d.year}/{d.month:02d}"


def parse_date_arg(token: str | None, *, today: date | None = None) -> tuple[date, str]:
    """`/networth [YYYY-MM-DD]` 用。token=None なら today。

    戻り値: (date, label)
    """
    today = today or date.today()
    if token is None:
        return today, today.strftime("%Y/%m/%d")
    m = _YYYY_MM_DD_RE.match(token)
    if not m:
        raise ValueError(f"日付形式が不正 (YYYY-MM-DD): {token!r}")
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        d = date(year, month, day)
    except ValueError as e:
        raise ValueError(f"日付が不正: {token!r}") from e
    return d, d.strftime("%Y/%m/%d")


__all__ = [
    "PeriodRange",
    "parse_date_arg",
    "parse_month_arg",
    "parse_summary_period",
]
