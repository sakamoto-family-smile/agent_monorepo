"""Phase 3-B: tool_executor.execute_tool の動作検証。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from services.tool_executor import execute_tool

JST = timezone(timedelta(hours=9), "Asia/Tokyo")


class _FakeRepo:
    def __init__(self, events: list[tuple]) -> None:
        self.events = events

    async def fetch_events_in_range(
        self, *, family_id: str, date_from: str, date_to: str
    ) -> list[tuple]:
        return [e for e in self.events if date_from <= e[1] <= date_to]


def _milk(date: str, hour: int = 12, ml: float = 100.0) -> tuple:
    ts = datetime.strptime(date, "%Y-%m-%d").replace(hour=hour, tzinfo=JST).isoformat()
    return (ts, date, "formula", ml, None, None, None, None, None, None, None, None)


def _wake(date: str, hour: int = 7, sleep_min: int = 480) -> tuple:
    ts = datetime.strptime(date, "%Y-%m-%d").replace(hour=hour, tzinfo=JST).isoformat()
    return (ts, date, "wake", None, None, None, sleep_min, None, None, None, None, None)


@pytest.mark.asyncio
async def test_query_events_count() -> None:
    repo = _FakeRepo([_milk("2026-02-01"), _milk("2026-02-02"), _milk("2026-03-01")])
    result_str = await execute_tool(
        name="query_events",
        args={
            "date_from": "2026-02-01",
            "date_to": "2026-02-28",
            "event_types": ["formula"],
            "aggregation": "count",
        },
        repo=repo,
        family_id="f1",
    )
    result = json.loads(result_str)
    assert result["value"] == 2
    assert result["aggregation"] == "count"


@pytest.mark.asyncio
async def test_query_events_sum_ml() -> None:
    repo = _FakeRepo(
        [
            _milk("2026-02-15", ml=100),
            _milk("2026-02-15", ml=120),
            _milk("2026-02-16", ml=80),
        ]
    )
    result_str = await execute_tool(
        name="query_events",
        args={
            "date_from": "2026-02-01",
            "date_to": "2026-02-28",
            "event_types": ["formula"],
            "aggregation": "sum_volume_ml",
        },
        repo=repo,
        family_id="f1",
    )
    result = json.loads(result_str)
    assert result["value"] == 300.0


@pytest.mark.asyncio
async def test_query_events_sum_sleep_minutes() -> None:
    repo = _FakeRepo([_wake("2026-02-15", sleep_min=540), _wake("2026-02-16", sleep_min=480)])
    result_str = await execute_tool(
        name="query_events",
        args={
            "date_from": "2026-02-01",
            "date_to": "2026-02-28",
            "event_types": ["wake"],
            "aggregation": "sum_sleep_minutes",
        },
        repo=repo,
        family_id="f1",
    )
    result = json.loads(result_str)
    assert result["value"] == 1020


@pytest.mark.asyncio
async def test_query_events_group_by_month() -> None:
    repo = _FakeRepo(
        [
            _milk("2026-02-15", ml=100),
            _milk("2026-02-20", ml=120),
            _milk("2026-03-05", ml=140),
        ]
    )
    result_str = await execute_tool(
        name="query_events",
        args={
            "date_from": "2026-02-01",
            "date_to": "2026-03-31",
            "event_types": ["formula"],
            "aggregation": "sum_volume_ml",
            "group_by": "month",
        },
        repo=repo,
        family_id="f1",
    )
    result = json.loads(result_str)
    assert result["groups"]["2026-02"] == 220.0
    assert result["groups"]["2026-03"] == 140.0


@pytest.mark.asyncio
async def test_query_events_raw_truncates() -> None:
    """raw aggregation は最大 50 件 + total_count フィールド。"""
    events = [_milk(f"2026-02-{i:02d}", ml=100) for i in range(1, 8)]  # 7 件
    repo = _FakeRepo(events)
    result_str = await execute_tool(
        name="query_events",
        args={
            "date_from": "2026-02-01",
            "date_to": "2026-02-28",
            "event_types": ["formula"],
            "aggregation": "raw",
        },
        repo=repo,
        family_id="f1",
    )
    result = json.loads(result_str)
    assert result["total_count"] == 7
    assert len(result["events"]) == 7


@pytest.mark.asyncio
async def test_ask_clarification_returns_question() -> None:
    repo = _FakeRepo([])
    result_str = await execute_tool(
        name="ask_clarification",
        args={"question": "回数ですか? 量 (ml) ですか?"},
        repo=repo,
        family_id="f1",
    )
    result = json.loads(result_str)
    assert result["question"] == "回数ですか? 量 (ml) ですか?"


@pytest.mark.asyncio
async def test_unknown_tool_raises() -> None:
    repo = _FakeRepo([])
    with pytest.raises(ValueError):
        await execute_tool(name="unknown_tool", args={}, repo=repo, family_id="f1")
