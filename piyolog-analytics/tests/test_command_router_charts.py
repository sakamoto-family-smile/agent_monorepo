"""Phase 1.5: command_router の chart コマンド振り分け検証。

chart コマンド (ミルク / 睡眠 / 体重 / 時間帯 / ダッシュボード) は
visualizer を呼び CommandResult.image_png に PNG を入れる。
EventRepo は monkeypatch で fetch_events_in_range を stub。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

JST = timezone(timedelta(hours=9), "Asia/Tokyo")


class _FakeRepo:
    def __init__(self, events: list[tuple]) -> None:
        self.events = events
        self.calls: list[dict[str, Any]] = []

    async def fetch_events_in_range(
        self, *, family_id: str, date_from: str, date_to: str
    ) -> list[tuple]:
        self.calls.append({"family_id": family_id, "date_from": date_from, "date_to": date_to})
        return self.events


def _milk(date: str, hour: int = 12, ml: float = 100.0) -> tuple:
    ts = datetime.strptime(date, "%Y-%m-%d").replace(hour=hour, tzinfo=JST).isoformat()
    return (ts, date, "formula", ml, None, None, None, None, None, None, None, None)


@pytest.mark.parametrize(
    "command",
    [
        "ミルク",
        "milk",
        "睡眠",
        "sleep",
        "体重",
        "weight",
        "時間帯",
        "heatmap",
        "ダッシュボード",
        "dashboard",
    ],
)
async def test_chart_commands_return_image_png(command: str) -> None:
    from services.command_router import handle_text_command

    repo = _FakeRepo([_milk("2026-04-26", 9, 100)])
    now = datetime(2026, 4, 27, 10, 0, tzinfo=JST)
    result = await handle_text_command(command, repo=repo, family_id="f1", now=now)
    assert result.image_png is not None
    assert result.chart_kind in {"milk", "sleep", "weight", "heatmap", "dashboard"}
    assert result.image_png[:8] == b"\x89PNG\r\n\x1a\n"


async def test_chart_command_no_data_returns_text_hint() -> None:
    from services.command_router import CHART_NO_DATA_HINT, handle_text_command

    repo = _FakeRepo([])
    now = datetime(2026, 4, 27, 10, 0, tzinfo=JST)
    result = await handle_text_command("ミルク", repo=repo, family_id="f1", now=now)
    assert result.image_png is None
    assert result.reply == CHART_NO_DATA_HINT


async def test_chart_command_period_override() -> None:
    """`ミルク 月間` で fetch 範囲が変わる。"""
    from services.command_router import handle_text_command

    repo = _FakeRepo([_milk("2026-04-26", 9, 100)])
    now = datetime(2026, 4, 27, 10, 0, tzinfo=JST)
    await handle_text_command("ミルク 月間", repo=repo, family_id="f1", now=now)
    # 月間: 4/1 ~ 4/27
    assert repo.calls
    assert repo.calls[-1]["date_from"] == "2026-04-01"
    assert repo.calls[-1]["date_to"] == "2026-04-27"


async def test_help_text_contains_chart_section() -> None:
    """HELP_TEXT に Phase 1.5 のグラフコマンド行が含まれていること。"""
    from services.command_router import HELP_TEXT

    assert "ミルク" in HELP_TEXT
    assert "ダッシュボード" in HELP_TEXT
    assert "Phase 1.5" in HELP_TEXT
    assert "期間" in HELP_TEXT  # 期間 syntax のヒント


async def test_chart_command_custom_period_syntax() -> None:
    """`ミルク 期間 YYYY-MM-DD YYYY-MM-DD` で任意範囲を fetch する。"""
    from services.command_router import handle_text_command

    repo = _FakeRepo([_milk("2026-02-15", 9, 100)])
    now = datetime(2026, 5, 3, 10, 0, tzinfo=JST)
    result = await handle_text_command(
        "ミルク 期間 2026-02-01 2026-02-28",
        repo=repo,
        family_id="f1",
        now=now,
    )
    assert result.image_png is not None
    assert repo.calls
    assert repo.calls[-1]["date_from"] == "2026-02-01"
    assert repo.calls[-1]["date_to"] == "2026-02-28"


async def test_chart_command_period_alias() -> None:
    """`dashboard period 2026-02-01 2026-02-28` も同じく動く (英語 alias)。"""
    from services.command_router import handle_text_command

    repo = _FakeRepo([_milk("2026-02-15", 9, 100)])
    now = datetime(2026, 5, 3, 10, 0, tzinfo=JST)
    result = await handle_text_command(
        "dashboard period 2026-02-01 2026-02-28",
        repo=repo,
        family_id="f1",
        now=now,
    )
    assert result.image_png is not None
    assert repo.calls[-1]["date_from"] == "2026-02-01"
    assert repo.calls[-1]["date_to"] == "2026-02-28"


async def test_chart_command_period_invalid_dates_returns_hint() -> None:
    """`ミルク 期間 hoge fuga` は INVALID_PERIOD_HINT。"""
    from services.command_router import INVALID_PERIOD_HINT, handle_text_command

    repo = _FakeRepo([_milk("2026-02-15", 9, 100)])
    now = datetime(2026, 5, 3, 10, 0, tzinfo=JST)
    result = await handle_text_command(
        "ミルク 期間 not-a-date 2026-02-28",
        repo=repo,
        family_id="f1",
        now=now,
    )
    assert result.image_png is None
    assert result.reply == INVALID_PERIOD_HINT


async def test_chart_command_period_missing_args_returns_hint() -> None:
    """`ミルク 期間 2026-02-01` (片方のみ) は INVALID_PERIOD_HINT。"""
    from services.command_router import INVALID_PERIOD_HINT, handle_text_command

    repo = _FakeRepo([])
    now = datetime(2026, 5, 3, 10, 0, tzinfo=JST)
    result = await handle_text_command(
        "ミルク 期間 2026-02-01",
        repo=repo,
        family_id="f1",
        now=now,
    )
    assert result.reply == INVALID_PERIOD_HINT
