"""Phase 2: Postback Router の action 振り分け検証。

EventRepo は monkeypatch で fetch_events_in_range / rollback_latest_batch を stub。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from models.piyolog import ImportBatch

JST = timezone(timedelta(hours=9), "Asia/Tokyo")


class _FakeRepo:
    def __init__(
        self,
        events: list[tuple] | None = None,
        rollback_batch: ImportBatch | None = None,
    ) -> None:
        self.events = events or []
        self.rollback_batch = rollback_batch
        self.fetch_calls: list[dict[str, Any]] = []
        self.rollback_calls: list[str] = []

    async def fetch_events_in_range(
        self, *, family_id: str, date_from: str, date_to: str
    ) -> list[tuple]:
        self.fetch_calls.append(
            {"family_id": family_id, "date_from": date_from, "date_to": date_to}
        )
        return self.events

    async def count_events(self, *, family_id: str) -> int:
        return len(self.events)

    async def rollback_latest_batch(self, *, family_id: str) -> ImportBatch | None:
        self.rollback_calls.append(family_id)
        return self.rollback_batch


def _milk(date: str, hour: int = 12, ml: float = 100.0) -> tuple:
    ts = datetime.strptime(date, "%Y-%m-%d").replace(hour=hour, tzinfo=JST).isoformat()
    return (ts, date, "formula", ml, None, None, None, None, None, None, None, None)


def _now() -> datetime:
    return datetime(2026, 5, 3, 10, 0, tzinfo=JST)


# ---- summary action ----


@pytest.mark.parametrize("period", ["today", "yesterday", "week", "month"])
async def test_postback_summary_preset_periods(period: str) -> None:
    from services.postback_router import handle_postback

    repo = _FakeRepo()
    result = await handle_postback(
        f"action=summary&period={period}", repo=repo, family_id="f1", now=_now()
    )
    assert result.image_png is None
    # サマリ text には日付のラベルが入る
    assert "2026" in result.reply


async def test_postback_summary_custom_period() -> None:
    from services.postback_router import handle_postback

    repo = _FakeRepo()
    result = await handle_postback(
        "action=summary&period=period&period_from=2026-02-01&period_to=2026-02-28",
        repo=repo,
        family_id="f1",
        now=_now(),
    )
    assert result.image_png is None
    assert "2026/02/01" in result.reply
    assert "2026/02/28" in result.reply


async def test_postback_summary_invalid_custom_period() -> None:
    from services.command_router import INVALID_PERIOD_HINT
    from services.postback_router import handle_postback

    result = await handle_postback(
        "action=summary&period=period&period_from=bad&period_to=2026-02-28",
        repo=_FakeRepo(),
        family_id="f1",
        now=_now(),
    )
    assert result.reply == INVALID_PERIOD_HINT


# ---- chart action ----


@pytest.mark.parametrize("kind", ["milk", "sleep", "weight", "heatmap", "dashboard"])
async def test_postback_chart_with_data(kind: str) -> None:
    from services.postback_router import handle_postback

    repo = _FakeRepo([_milk("2026-04-26", 9, 100)])
    result = await handle_postback(
        f"action=chart&kind={kind}&period=week",
        repo=repo,
        family_id="f1",
        now=_now(),
    )
    assert result.image_png is not None
    assert result.image_png[:8] == b"\x89PNG\r\n\x1a\n"
    assert result.chart_kind == kind


async def test_postback_chart_custom_period() -> None:
    from services.postback_router import handle_postback

    repo = _FakeRepo([_milk("2026-02-15", 9, 100)])
    result = await handle_postback(
        "action=chart&kind=milk&period_from=2026-02-01&period_to=2026-02-28",
        repo=repo,
        family_id="f1",
        now=_now(),
    )
    assert result.image_png is not None
    assert repo.fetch_calls[-1]["date_from"] == "2026-02-01"
    assert repo.fetch_calls[-1]["date_to"] == "2026-02-28"


async def test_postback_chart_default_period_per_kind() -> None:
    """period 指定なし: weight/heatmap は month、それ以外は week。"""
    from services.postback_router import handle_postback

    repo_weight = _FakeRepo([_milk("2026-05-01", 9, 100)])
    await handle_postback(
        "action=chart&kind=weight",
        repo=repo_weight,
        family_id="f1",
        now=_now(),
    )
    # 月間: 5/1 〜 5/3
    assert repo_weight.fetch_calls[-1]["date_from"] == "2026-05-01"

    repo_milk = _FakeRepo([_milk("2026-04-26", 9, 100)])
    await handle_postback(
        "action=chart&kind=milk",
        repo=repo_milk,
        family_id="f1",
        now=_now(),
    )
    # 週間: 4/27 〜 5/3 (= 7 日間)
    assert repo_milk.fetch_calls[-1]["date_from"] == "2026-04-27"
    assert repo_milk.fetch_calls[-1]["date_to"] == "2026-05-03"


async def test_postback_chart_invalid_kind_returns_unknown() -> None:
    from services.command_router import UNKNOWN_HINT
    from services.postback_router import handle_postback

    result = await handle_postback(
        "action=chart&kind=invalid",
        repo=_FakeRepo(),
        family_id="f1",
        now=_now(),
    )
    assert result.reply == UNKNOWN_HINT


async def test_postback_chart_no_data_returns_hint() -> None:
    from services.command_router import CHART_NO_DATA_HINT
    from services.postback_router import handle_postback

    repo = _FakeRepo([])
    result = await handle_postback(
        "action=chart&kind=milk&period=week",
        repo=repo,
        family_id="f1",
        now=_now(),
    )
    assert result.reply == CHART_NO_DATA_HINT


# ---- help / undo / consult / unknown ----


async def test_postback_help() -> None:
    from services.postback_router import handle_postback

    result = await handle_postback("action=help", repo=_FakeRepo(), family_id="f1", now=_now())
    assert "ぴよログ分析" in result.reply


async def test_postback_undo_with_active_batch() -> None:
    from services.postback_router import handle_postback

    batch = ImportBatch(
        batch_id="b" + "0" * 31,
        family_id="f1",
        source_user_id="U1",
        source_filename="day1.txt",
        raw_text_hash="h" * 16,
        event_count=5,
        imported_at="2026-05-03T03:00:00+00:00",
        rolled_back_at="2026-05-03T05:00:00+00:00",
    )
    repo = _FakeRepo(rollback_batch=batch)
    result = await handle_postback("action=undo", repo=repo, family_id="f1", now=_now())
    assert "取り消しました" in result.reply
    assert "day1.txt" in result.reply
    assert repo.rollback_calls == ["f1"]


async def test_postback_undo_no_active_batch() -> None:
    from services.command_router import UNDO_NO_BATCH_HINT
    from services.postback_router import handle_postback

    result = await handle_postback("action=undo", repo=_FakeRepo(), family_id="f1", now=_now())
    assert result.reply == UNDO_NO_BATCH_HINT


async def test_postback_consult_returns_stub() -> None:
    from services.postback_router import CONSULT_STUB_REPLY, handle_postback

    result = await handle_postback(
        "action=consult&op=enter",
        repo=_FakeRepo(),
        family_id="f1",
        now=_now(),
    )
    assert result.reply == CONSULT_STUB_REPLY


async def test_postback_unknown_action() -> None:
    from services.command_router import UNKNOWN_HINT
    from services.postback_router import handle_postback

    result = await handle_postback("action=mystery", repo=_FakeRepo(), family_id="f1", now=_now())
    assert result.reply == UNKNOWN_HINT


async def test_postback_empty_data() -> None:
    from services.command_router import UNKNOWN_HINT
    from services.postback_router import handle_postback

    result = await handle_postback("", repo=_FakeRepo(), family_id="f1", now=_now())
    assert result.reply == UNKNOWN_HINT


# ---- Phase 4-B: settings UI ----


class _FakeChildRepo:
    def __init__(self, *, birth_date: str | None = None, name: str | None = None) -> None:
        self._birth_date = birth_date
        self._name = name
        self.upsert_birth_date_calls: list[tuple[str, str, str]] = []

    async def get(self, *, family_id: str, child_id: str):
        if self._birth_date is None and self._name is None:
            return None
        from repositories.child_repo import Child

        return Child(
            family_id=family_id,
            child_id=child_id,
            birth_date=self._birth_date,
            name=self._name,
            updated_at="2026-05-05T00:00:00+00:00",
        )

    async def upsert_birth_date(
        self, *, family_id: str, child_id: str, birth_date: str
    ):
        from repositories.child_repo import Child, is_valid_birth_date

        if not is_valid_birth_date(birth_date):
            raise ValueError(birth_date)
        self.upsert_birth_date_calls.append((family_id, child_id, birth_date))
        self._birth_date = birth_date
        return Child(
            family_id=family_id,
            child_id=child_id,
            birth_date=birth_date,
            name=self._name,
            updated_at="2026-05-05T00:00:00+00:00",
        )


async def test_postback_settings_returns_quick_reply_with_no_initial() -> None:
    from services.postback_router import SETTINGS_PROMPT, handle_postback

    cr = _FakeChildRepo()
    result = await handle_postback(
        "action=settings", repo=_FakeRepo(), family_id="f1", child_repo=cr, now=_now()
    )
    assert result.reply == SETTINGS_PROMPT
    assert len(result.quick_reply) == 3
    # 1 つ目は datetime picker
    dp = result.quick_reply[0]
    assert dp.kind == "datetimepicker"
    assert dp.mode == "date"
    assert dp.data == "action=child_set_birth_date"
    assert dp.initial is None  # 未登録なので initial なし
    # 2 つ目は postback (名前)
    assert result.quick_reply[1].kind == "postback"
    assert result.quick_reply[1].data == "action=child_set_name"
    # 3 つ目は postback (キャンセル)
    assert result.quick_reply[2].data == "action=settings_cancel"


async def test_postback_settings_uses_existing_birth_date_as_initial() -> None:
    from services.postback_router import handle_postback

    cr = _FakeChildRepo(birth_date="2025-08-15")
    result = await handle_postback(
        "action=settings", repo=_FakeRepo(), family_id="f1", child_repo=cr, now=_now()
    )
    assert result.quick_reply[0].initial == "2025-08-15"


async def test_postback_settings_cancel() -> None:
    from services.postback_router import SETTINGS_CANCELLED, handle_postback

    result = await handle_postback(
        "action=settings_cancel", repo=_FakeRepo(), family_id="f1", now=_now()
    )
    assert result.reply == SETTINGS_CANCELLED


async def test_postback_child_set_birth_date_persists() -> None:
    from services.postback_router import handle_postback

    cr = _FakeChildRepo()
    result = await handle_postback(
        "action=child_set_birth_date",
        repo=_FakeRepo(),
        family_id="f1",
        postback_params={"date": "2025-08-15"},
        child_repo=cr,
        default_child_id="default",
        now=_now(),
    )
    assert "2025-08-15" in result.reply
    assert cr.upsert_birth_date_calls == [("f1", "default", "2025-08-15")]


async def test_postback_child_set_birth_date_rejects_invalid_date() -> None:
    from services.postback_router import (
        SETTINGS_BIRTH_DATE_INVALID,
        handle_postback,
    )

    cr = _FakeChildRepo()
    result = await handle_postback(
        "action=child_set_birth_date",
        repo=_FakeRepo(),
        family_id="f1",
        postback_params={"date": "bad-date"},
        child_repo=cr,
        now=_now(),
    )
    assert result.reply == SETTINGS_BIRTH_DATE_INVALID
    assert cr.upsert_birth_date_calls == []


async def test_postback_child_set_birth_date_without_repo() -> None:
    from services.postback_router import (
        SETTINGS_REPO_UNAVAILABLE,
        handle_postback,
    )

    result = await handle_postback(
        "action=child_set_birth_date",
        repo=_FakeRepo(),
        family_id="f1",
        postback_params={"date": "2025-08-15"},
        child_repo=None,
        now=_now(),
    )
    assert result.reply == SETTINGS_REPO_UNAVAILABLE


async def test_postback_child_set_name_returns_prompt() -> None:
    from services.postback_router import SETTINGS_NAME_PROMPT, handle_postback

    result = await handle_postback(
        "action=child_set_name",
        repo=_FakeRepo(),
        family_id="f1",
        now=_now(),
    )
    assert result.reply == SETTINGS_NAME_PROMPT
