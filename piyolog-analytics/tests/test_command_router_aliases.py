"""Phase 1 残 TODO: コマンド aliases (半角/全角空白、大文字小文字、頭スラッシュ) の検証。

Phase 1 は handle_text_command 経由で動作確認するため、EventRepo は in-memory stub。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

JST = timezone(timedelta(hours=9), "Asia/Tokyo")


class _StubRepo:
    async def fetch_events_in_range(
        self, *, family_id: str, date_from: str, date_to: str
    ) -> list[tuple]:
        return []

    async def count_events(self, *, family_id: str) -> int:
        return 0


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 4, 27, 10, 0, tzinfo=JST)


@pytest.mark.parametrize(
    "raw",
    [
        "今日",
        " 今日 ",
        "\u3000今日\u3000",  # 全角空白
        "today",
        "TODAY",
        " /today",
    ],
)
async def test_today_aliases_route_to_summary(raw: str, now: datetime) -> None:
    from services.command_router import handle_text_command

    result = await handle_text_command(raw, repo=_StubRepo(), family_id="f1", now=now)
    # サマリ応答 (テキスト)、image_png None
    assert result.image_png is None
    # text reply は今日のサマリ (期間ラベル "2026/04/27" を含む)
    assert "2026/04/27" in result.reply


@pytest.mark.parametrize(
    "raw, expected_keyword",
    [
        ("ヘルプ", "ぴよログ分析"),
        ("HELP", "ぴよログ分析"),
        ("？", "ぴよログ分析"),
    ],
)
async def test_help_aliases(raw: str, expected_keyword: str, now: datetime) -> None:
    from services.command_router import handle_text_command

    result = await handle_text_command(raw, repo=_StubRepo(), family_id="f1", now=now)
    assert expected_keyword in result.reply


async def test_unknown_command_returns_hint(now: datetime) -> None:
    from services.command_router import UNKNOWN_HINT, handle_text_command

    result = await handle_text_command("ぴよぴよ", repo=_StubRepo(), family_id="f1", now=now)
    assert result.reply == UNKNOWN_HINT


async def test_period_command_with_invalid_dates(now: datetime) -> None:
    from services.command_router import INVALID_PERIOD_HINT, handle_text_command

    # 引数欠損
    result = await handle_text_command("期間 2026-04-01", repo=_StubRepo(), family_id="f1", now=now)
    assert result.reply == INVALID_PERIOD_HINT


async def test_chart_command_lower_case(now: datetime) -> None:
    """chart コマンドの大文字小文字混在許容を検証。"""
    from services.command_router import handle_text_command

    result = await handle_text_command("MILK", repo=_StubRepo(), family_id="f1", now=now)
    # _StubRepo はイベント無 → CHART_NO_DATA_HINT が返る
    from services.command_router import CHART_NO_DATA_HINT

    assert result.reply == CHART_NO_DATA_HINT
