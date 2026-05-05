"""PR 2: line_period の純関数テスト。"""

from __future__ import annotations

from datetime import date

import pytest
from services.line_period import (
    parse_date_arg,
    parse_month_arg,
    parse_summary_period,
)

# ---- parse_summary_period ----


def test_no_args_returns_this_month():
    today = date(2025, 10, 15)
    p = parse_summary_period([], today=today)
    assert p.start == date(2025, 10, 1)
    assert p.end == date(2025, 10, 31)
    assert p.label == "2025/10"


def test_kw_kongetsu():
    today = date(2025, 10, 15)
    p = parse_summary_period(["今月"], today=today)
    assert p.start == date(2025, 10, 1)
    assert p.end == date(2025, 10, 31)


def test_kw_sengetsu():
    today = date(2025, 10, 15)
    p = parse_summary_period(["先月"], today=today)
    assert p.start == date(2025, 9, 1)
    assert p.end == date(2025, 9, 30)
    assert p.label == "2025/09"


def test_kw_sengetsu_january_rollover():
    today = date(2025, 1, 15)
    p = parse_summary_period(["先月"], today=today)
    assert p.start == date(2024, 12, 1)
    assert p.end == date(2024, 12, 31)


def test_kw_kotoshi():
    today = date(2025, 10, 15)
    p = parse_summary_period(["今年"], today=today)
    assert p.start == date(2025, 1, 1)
    assert p.end == date(2025, 10, 15)
    assert "2025/01" in p.label and "2025/10" in p.label


def test_single_yyyy_mm():
    p = parse_summary_period(["2024-02"], today=date(2025, 10, 15))
    assert p.start == date(2024, 2, 1)
    # 2024 is leap year → Feb 29
    assert p.end == date(2024, 2, 29)
    assert p.label == "2024/02"


def test_range_yyyy_mm_yyyy_mm():
    p = parse_summary_period(["2025-04", "2025-09"], today=date(2025, 10, 15))
    assert p.start == date(2025, 4, 1)
    assert p.end == date(2025, 9, 30)
    assert p.label == "2025/04〜2025/09"


def test_invalid_token():
    with pytest.raises(ValueError, match="期間指定が不正"):
        parse_summary_period(["foo"])


def test_invalid_yyyy_mm_format():
    # `2025/10` は YYYY-MM regex に不一致 → "期間指定が不正" として弾かれる
    with pytest.raises(ValueError):
        parse_summary_period(["2025/10"])


def test_invalid_month():
    with pytest.raises(ValueError, match="月が不正"):
        parse_summary_period(["2025-13"])


def test_end_before_start():
    with pytest.raises(ValueError, match="終了月が開始月より前"):
        parse_summary_period(["2025-09", "2025-04"])


def test_too_many_args():
    with pytest.raises(ValueError, match="多すぎ"):
        parse_summary_period(["2025-04", "2025-09", "2025-10"])


# ---- parse_month_arg ----


def test_parse_month_arg_none_returns_today_month():
    today = date(2025, 10, 15)
    d, label = parse_month_arg(None, today=today)
    assert d == date(2025, 10, 1)
    assert label == "2025/10"


def test_parse_month_arg_kw_kongetsu():
    d, _ = parse_month_arg("今月", today=date(2025, 10, 15))
    assert d == date(2025, 10, 1)


def test_parse_month_arg_kw_sengetsu():
    d, _ = parse_month_arg("先月", today=date(2025, 10, 15))
    assert d == date(2025, 9, 1)


def test_parse_month_arg_yyyy_mm():
    d, label = parse_month_arg("2025-08")
    assert d == date(2025, 8, 1)
    assert label == "2025/08"


def test_parse_month_arg_invalid():
    with pytest.raises(ValueError):
        parse_month_arg("not-a-date")


# ---- parse_date_arg ----


def test_parse_date_arg_none_returns_today():
    today = date(2025, 10, 15)
    d, label = parse_date_arg(None, today=today)
    assert d == today
    assert label == "2025/10/15"


def test_parse_date_arg_yyyy_mm_dd():
    d, label = parse_date_arg("2024-12-31")
    assert d == date(2024, 12, 31)
    assert label == "2024/12/31"


def test_parse_date_arg_invalid_format():
    with pytest.raises(ValueError, match="日付形式が不正"):
        parse_date_arg("2025/10/15")


def test_parse_date_arg_invalid_date():
    with pytest.raises(ValueError):
        parse_date_arg("2025-02-30")
