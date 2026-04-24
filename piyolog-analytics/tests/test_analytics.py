"""analytics.py の集計とテキスト整形テスト。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from conftest import load_fixture
from parser.piyolog_parser import parse_piyolog_text
from repositories.event_repo import EventRepo
from services.analytics import (
    render_summary_text,
    resolve_period,
    summarize,
)

JST = timezone(timedelta(hours=9), "Asia/Tokyo")


# ---------------------------------------------------------------------------
# resolve_period
# ---------------------------------------------------------------------------


def test_resolve_period_today():
    now = datetime(2026, 4, 24, 9, 0, tzinfo=JST)
    f, t, label = resolve_period("today", now=now)
    assert f == t
    assert f.isoformat() == "2026-04-24"


def test_resolve_period_yesterday():
    now = datetime(2026, 4, 24, 9, 0, tzinfo=JST)
    f, t, _ = resolve_period("yesterday", now=now)
    assert f == t
    assert f.isoformat() == "2026-04-23"


def test_resolve_period_week_is_last_7_days_inclusive():
    now = datetime(2026, 4, 24, 9, 0, tzinfo=JST)
    f, t, _ = resolve_period("week", now=now)
    # 04-18 〜 04-24 の 7 日
    assert f.isoformat() == "2026-04-18"
    assert t.isoformat() == "2026-04-24"


def test_resolve_period_month_starts_first_of_month():
    now = datetime(2026, 4, 24, 9, 0, tzinfo=JST)
    f, t, _ = resolve_period("month", now=now)
    assert f.isoformat() == "2026-04-01"
    assert t.isoformat() == "2026-04-24"


def test_resolve_period_custom_range_normalizes_order():
    f, t, _ = resolve_period(
        "period", custom_from="2026-04-23", custom_to="2026-04-20"
    )
    assert f.isoformat() == "2026-04-20"
    assert t.isoformat() == "2026-04-23"


def test_resolve_period_unknown_raises():
    with pytest.raises(ValueError):
        resolve_period("decade")


# ---------------------------------------------------------------------------
# summarize end-to-end
# ---------------------------------------------------------------------------


@pytest.fixture
async def repo_with_daily(tmp_path):
    text = load_fixture("daily_sample.txt")
    events = parse_piyolog_text(text).days[0].events
    r = EventRepo(db_path=str(tmp_path / "t.db"))
    await r.initialize()
    await r.import_events(
        family_id="fam1",
        source_user_id="Utest1",
        child_id="default",
        raw_text=text,
        source_filename=None,
        events=events,
    )
    return r


@pytest.mark.asyncio
async def test_summarize_today_matches_fixture(repo_with_daily: EventRepo):
    now = datetime(2026, 4, 22, 23, 59, tzinfo=JST)
    s = await summarize(repo=repo_with_daily, family_id="fam1", period="today", now=now)
    assert s.formula_count == 2
    assert s.formula_total_ml == 260.0
    assert s.expressed_milk_count == 1
    assert s.expressed_milk_total_ml == 80.0
    assert s.breast_milk_count == 1
    assert s.breast_milk_left_minutes == 5
    assert s.breast_milk_right_minutes == 5
    # 8時間30分 + 2時間0分 = 630 分
    assert s.sleep_total_minutes == 630
    assert s.pee_count == 1
    assert s.poo_count == 1
    assert s.baby_food_count == 1
    assert s.bath_count == 1
    assert s.medicine_count == 1
    assert s.latest_temperature_c == 36.8
    assert s.latest_weight_kg == 8.5
    assert s.latest_height_cm == 72.0


@pytest.mark.asyncio
async def test_summarize_empty_returns_zero(repo_with_daily: EventRepo):
    now = datetime(2026, 5, 1, 9, 0, tzinfo=JST)
    s = await summarize(repo=repo_with_daily, family_id="fam1", period="today", now=now)
    assert s.total_events == 0
    assert s.formula_count == 0


# ---------------------------------------------------------------------------
# render_summary_text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_render_summary_contains_key_stats(repo_with_daily: EventRepo):
    now = datetime(2026, 4, 22, 23, 59, tzinfo=JST)
    s = await summarize(repo=repo_with_daily, family_id="fam1", period="today", now=now)
    text = render_summary_text(s)
    assert "サマリ" in text
    assert "ミルク" in text
    assert "260ml" in text
    assert "搾母乳" in text
    assert "母乳" in text
    assert "睡眠" in text
    assert "36.8°C" in text
    assert "8.50kg" in text or "8.5kg" in text


@pytest.mark.asyncio
async def test_render_summary_empty_message(repo_with_daily: EventRepo):
    now = datetime(2026, 5, 1, 9, 0, tzinfo=JST)
    s = await summarize(repo=repo_with_daily, family_id="fam1", period="today", now=now)
    text = render_summary_text(s)
    assert "記録がありません" in text
