"""ぴよログパーサのユニットテスト。

カバーする観点:
  - daily / monthly 両フォーマット
  - 主要イベント型の値抽出 (ミルク ml / 母乳 左右分 / 起床 睡眠時間 / 体温 / 体重 / 身長 / 頭囲 / うんち 性状)
  - 搾母乳とミルクの区別
  - 左/右どちらかのみの母乳
  - 未知イベントのフォールバック (OTHER + memo)
  - 数値欠落のフォールバック (ミルク(完食) → memo)
  - コメント抽出
  - 合計行スキップ (event 数に含まれない)
"""

from __future__ import annotations

from conftest import load_fixture
from models.piyolog import EventType
from parser.piyolog_parser import parse_piyolog_text


def test_parse_daily_sample_total_events():
    text = load_fixture("daily_sample.txt")
    result = parse_piyolog_text(text)
    assert len(result.days) == 1
    day = result.days[0]
    assert day.date.year == 2026 and day.date.month == 4 and day.date.day == 22
    # daily_sample.txt の event 行は 16 件 (合計行は含まれない)
    assert len(day.events) == 16


def test_parse_daily_baby_info():
    text = load_fixture("daily_sample.txt")
    result = parse_piyolog_text(text)
    day = result.days[0]
    assert day.baby_name == "さくら"
    assert day.age_years == 1
    assert day.age_months == 2
    assert day.age_days == 3


def test_parse_daily_comment():
    text = load_fixture("daily_sample.txt")
    result = parse_piyolog_text(text)
    assert result.days[0].comment is not None
    assert "離乳食" in result.days[0].comment


def test_formula_ml_extracted():
    text = load_fixture("daily_sample.txt")
    result = parse_piyolog_text(text)
    formulas = [e for e in result.days[0].events if e.event_type == EventType.FORMULA]
    assert len(formulas) == 2
    assert {e.volume_ml for e in formulas} == {120.0, 140.0}


def test_breast_milk_left_right_minutes():
    text = load_fixture("daily_sample.txt")
    result = parse_piyolog_text(text)
    bms = [e for e in result.days[0].events if e.event_type == EventType.BREAST_MILK]
    assert len(bms) == 1
    assert bms[0].left_minutes == 5
    assert bms[0].right_minutes == 5


def test_wake_sleep_minutes():
    text = load_fixture("daily_sample.txt")
    result = parse_piyolog_text(text)
    wakes = [e for e in result.days[0].events if e.event_type == EventType.WAKE]
    assert len(wakes) == 2
    minutes = sorted(e.sleep_minutes for e in wakes if e.sleep_minutes is not None)
    # 8h30m = 510 分, 2h0m = 120 分
    assert minutes == [120, 510]


def test_expressed_milk_separate_from_formula():
    text = load_fixture("daily_sample.txt")
    result = parse_piyolog_text(text)
    expressed = [e for e in result.days[0].events if e.event_type == EventType.EXPRESSED_MILK]
    assert len(expressed) == 1
    assert expressed[0].volume_ml == 80.0
    # 搾母乳は FORMULA に混入しない
    formulas = [e for e in result.days[0].events if e.event_type == EventType.FORMULA]
    assert all(e.volume_ml in (120.0, 140.0) for e in formulas)


def test_weight_height_temperature_extracted():
    text = load_fixture("daily_sample.txt")
    result = parse_piyolog_text(text)
    events = result.days[0].events
    weight = next(e for e in events if e.event_type == EventType.WEIGHT)
    height = next(e for e in events if e.event_type == EventType.HEIGHT)
    temp = next(e for e in events if e.event_type == EventType.TEMPERATURE)
    assert weight.weight_kg == 8.5
    assert height.height_cm == 72.0
    assert temp.temperature_c == 36.8


def test_poo_consistency_stored_as_memo():
    text = load_fixture("daily_sample.txt")
    result = parse_piyolog_text(text)
    poos = [e for e in result.days[0].events if e.event_type == EventType.POO]
    assert len(poos) == 1
    assert poos[0].memo == "ふつう"


def test_parse_monthly_sample_two_days():
    text = load_fixture("monthly_sample.txt")
    result = parse_piyolog_text(text)
    assert len(result.days) == 2
    assert result.days[0].date.day == 22
    assert result.days[1].date.day == 23


def test_monthly_second_day_events_and_totals_skipped():
    text = load_fixture("monthly_sample.txt")
    result = parse_piyolog_text(text)
    day2 = result.days[1]
    # 7 件のイベント (起きる / うんち / ミルク / 頭囲 / 体温 / お風呂 / 寝る)
    assert len(day2.events) == 7
    head = next(e for e in day2.events if e.event_type == EventType.HEAD_CIRCUMFERENCE)
    assert head.head_circumference_cm == 45.5


def test_monthly_left_only_breast_milk():
    text = load_fixture("edge_cases.txt")
    result = parse_piyolog_text(text)
    bms = [e for e in result.days[0].events if e.event_type == EventType.BREAST_MILK]
    # 左のみ / 右のみ 2 件
    left_only = [e for e in bms if e.left_minutes == 10 and e.right_minutes is None]
    right_only = [e for e in bms if e.right_minutes == 8 and e.left_minutes is None]
    assert len(left_only) == 1
    assert len(right_only) == 1


def test_unknown_event_falls_back_to_other_with_memo():
    text = load_fixture("edge_cases.txt")
    result = parse_piyolog_text(text)
    others = [e for e in result.days[0].events if e.event_type == EventType.OTHER]
    assert len(others) == 1
    assert "未知イベント" in (others[0].memo or "")


def test_formula_without_ml_stores_memo_fallback():
    text = load_fixture("edge_cases.txt")
    result = parse_piyolog_text(text)
    formulas = [e for e in result.days[0].events if e.event_type == EventType.FORMULA]
    no_ml = [e for e in formulas if e.volume_ml is None]
    assert len(no_ml) == 1
    assert "完食" in (no_ml[0].memo or "")


def test_poo_without_detail_has_null_memo():
    text = load_fixture("edge_cases.txt")
    result = parse_piyolog_text(text)
    poos = [e for e in result.days[0].events if e.event_type == EventType.POO]
    assert len(poos) == 1
    # "うんち" のみで性状なし → memo は None
    assert poos[0].memo is None


def test_temperature_extraction_preserves_decimal():
    text = load_fixture("edge_cases.txt")
    result = parse_piyolog_text(text)
    temps = [e for e in result.days[0].events if e.event_type == EventType.TEMPERATURE]
    assert temps[0].temperature_c == 38.1


def test_timestamps_are_jst_aware():
    text = load_fixture("daily_sample.txt")
    result = parse_piyolog_text(text)
    for e in result.days[0].events:
        assert e.timestamp.tzinfo is not None
        assert e.timestamp.utcoffset().total_seconds() == 9 * 3600


def test_empty_text_yields_no_days():
    result = parse_piyolog_text("")
    assert result.days == []
    assert result.total_events == 0


def test_total_events_sums_across_days():
    text = load_fixture("monthly_sample.txt")
    result = parse_piyolog_text(text)
    assert result.total_events == sum(len(d.events) for d in result.days)
