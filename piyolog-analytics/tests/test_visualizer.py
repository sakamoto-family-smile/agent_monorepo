"""Phase 1.5: visualizer.py の各グラフが PNG bytes を返すことを検証。

画像差分比較はせず、最小条件:
- 戻り値が bytes
- 先頭 8 バイトが PNG マジック (89 50 4E 47 0D 0A 1A 0A)
- 空 events / 一部欠損 events でも crash しない (空グラフを返す)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services import visualizer

JST = timezone(timedelta(hours=9), "Asia/Tokyo")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _ts(yyyy_mm_dd: str, hour: int = 12, minute: int = 0) -> str:
    """YYYY-MM-DD + hour → ISO8601 (+09:00) 文字列。"""
    d = datetime.strptime(yyyy_mm_dd, "%Y-%m-%d").replace(hour=hour, minute=minute, tzinfo=JST)
    return d.isoformat()


def _milk_event(date: str, hour: int = 12, ml: float = 100.0) -> tuple:
    """fetch_events_in_range の戻り値タプル形式 (12 要素) でミルクイベント生成。"""
    return (
        _ts(date, hour),  # 0 event_timestamp
        date,  # 1 event_date
        "formula",  # 2 event_type
        ml,  # 3 volume_ml
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    )


def _wake_event(date: str, hour: int = 7, sleep_min: int = 480) -> tuple:
    return (
        _ts(date, hour),
        date,
        "wake",
        None,
        None,
        None,
        sleep_min,  # 6 sleep_minutes
        None,
        None,
        None,
        None,
        None,
    )


def _weight_event(date: str, kg: float) -> tuple:
    return (
        _ts(date, 8),
        date,
        "weight",
        None,
        None,
        None,
        None,
        None,
        kg,  # 8 weight_kg
        None,
        None,
        None,
    )


def _is_png(data: bytes) -> bool:
    return data[:8] == PNG_MAGIC


# ---- empty inputs ----


def test_milk_timeline_empty_returns_png() -> None:
    out = visualizer.milk_timeline([])
    assert isinstance(out, bytes)
    assert _is_png(out)


def test_sleep_timeline_empty_returns_png() -> None:
    out = visualizer.sleep_timeline([])
    assert _is_png(out)


def test_weight_height_timeline_empty_returns_png() -> None:
    out = visualizer.weight_height_timeline([])
    assert _is_png(out)


def test_feeding_heatmap_empty_returns_png() -> None:
    out = visualizer.feeding_heatmap([])
    assert _is_png(out)


def test_dashboard_empty_returns_png() -> None:
    out = visualizer.dashboard([])
    assert _is_png(out)


# ---- with data ----


def test_milk_timeline_with_data() -> None:
    events = [
        _milk_event("2026-04-26", 9, 100),
        _milk_event("2026-04-26", 13, 120),
        _milk_event("2026-04-27", 10, 110),
    ]
    out = visualizer.milk_timeline(events, period="week")
    assert _is_png(out)


def test_sleep_timeline_with_data() -> None:
    events = [
        _wake_event("2026-04-26", 7, 540),
        _wake_event("2026-04-27", 6, 600),
    ]
    out = visualizer.sleep_timeline(events)
    assert _is_png(out)


def test_weight_height_timeline_with_mixed_metrics() -> None:
    events = [
        _weight_event("2026-04-01", 5.2),
        _weight_event("2026-04-15", 5.8),
        # height + head も入れて twin axis 確認
        (
            _ts("2026-04-01", 8),
            "2026-04-01",
            "height",
            None,
            None,
            None,
            None,
            None,
            None,
            58.0,
            None,
            None,
        ),
        (
            _ts("2026-04-15", 8),
            "2026-04-15",
            "head_circumference",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            39.0,
            None,
        ),
    ]
    out = visualizer.weight_height_timeline(events, period="month")
    assert _is_png(out)


def test_feeding_heatmap_with_data() -> None:
    events = [
        _milk_event("2026-04-26", 3, 100),
        _milk_event("2026-04-26", 9, 100),
        _milk_event("2026-04-27", 14, 110),
        _milk_event("2026-04-28", 21, 95),
    ]
    out = visualizer.feeding_heatmap(events, period="week")
    assert _is_png(out)


def test_dashboard_with_partial_data() -> None:
    """ダッシュボードはミルクのみあって睡眠なし等のケースでも crash しない。"""
    events = [
        _milk_event("2026-04-26", 9, 100),
        _milk_event("2026-04-27", 13, 110),
    ]
    out = visualizer.dashboard(events, period="week")
    assert _is_png(out)
