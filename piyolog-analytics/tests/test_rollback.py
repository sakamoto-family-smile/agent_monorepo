"""Phase 1.5: rollback_latest_batch の挙動。

SQLite in-memory DB を立て、import → rollback → 再 import が成立することを検証。
集計クエリ (`count_events`) が rolled_back を除外することも合わせて確認。
"""

from __future__ import annotations

import asyncio
import pathlib
import tempfile
from datetime import UTC, datetime

import pytest
from models.piyolog import EventType, ParsedEvent
from repositories.event_repo import EventRepo

JST = datetime.now(UTC).astimezone()  # 単に timezone-aware にするための placeholder


@pytest.fixture
async def repo():
    """各テスト独立な SQLite ファイル DB。in-memory だと EventRepo の engine 共有で
    別接続が見えないため tempfile を使う (lifeplanner-agent の流儀準拠)。"""
    with tempfile.TemporaryDirectory() as td:
        db_path = pathlib.Path(td) / "test.db"
        repo = EventRepo(database_url=f"sqlite+aiosqlite:///{db_path}")
        await repo.initialize()
        yield repo
        await repo.dispose()


def _sample_events(date: str = "2026-04-26") -> list[ParsedEvent]:
    """1 日分のミルク 2 件 + wake 1 件。"""
    base = datetime.fromisoformat(f"{date}T09:00:00+09:00")
    return [
        ParsedEvent(
            timestamp=base,
            event_type=EventType.FORMULA,
            raw_text=f"09:00 ミルク 100ml ({date})",
            volume_ml=100.0,
        ),
        ParsedEvent(
            timestamp=base.replace(hour=14),
            event_type=EventType.FORMULA,
            raw_text=f"14:00 ミルク 120ml ({date})",
            volume_ml=120.0,
        ),
        ParsedEvent(
            timestamp=base.replace(hour=7),
            event_type=EventType.WAKE,
            raw_text=f"07:00 起きる ({date})",
            sleep_minutes=480,
        ),
    ]


@pytest.mark.asyncio
async def test_rollback_latest_batch_marks_batch_rolled_back(repo: EventRepo) -> None:
    events = _sample_events()
    batch = await repo.import_events(
        family_id="f1",
        source_user_id="U1",
        child_id="default",
        raw_text="raw1",
        source_filename="day1.txt",
        events=events,
    )
    assert batch.rolled_back_at is None

    # rollback
    rolled = await repo.rollback_latest_batch(family_id="f1")
    assert rolled is not None
    assert rolled.batch_id == batch.batch_id
    assert rolled.rolled_back_at is not None
    assert rolled.event_count == 3
    assert rolled.source_filename == "day1.txt"


@pytest.mark.asyncio
async def test_rollback_excludes_events_from_aggregation(repo: EventRepo) -> None:
    """rollback 後は count_events / fetch_events_in_range で見えなくなる。"""
    await repo.import_events(
        family_id="f1",
        source_user_id="U1",
        child_id="default",
        raw_text="raw-a",
        source_filename="day1.txt",
        events=_sample_events("2026-04-26"),
    )
    pre_count = await repo.count_events(family_id="f1")
    assert pre_count == 3

    await repo.rollback_latest_batch(family_id="f1")
    post_count = await repo.count_events(family_id="f1")
    assert post_count == 0

    events = await repo.fetch_events_in_range(
        family_id="f1", date_from="2026-04-26", date_to="2026-04-26"
    )
    assert events == []


@pytest.mark.asyncio
async def test_rollback_allows_reimport_of_same_raw_text(repo: EventRepo) -> None:
    """rollback 後は同じ raw_text を再 import できる (partial unique index 効果)。"""
    raw = "duplicated-raw"
    await repo.import_events(
        family_id="f1",
        source_user_id="U1",
        child_id="default",
        raw_text=raw,
        source_filename="day1.txt",
        events=_sample_events(),
    )
    await repo.rollback_latest_batch(family_id="f1")

    # 再 import できる (DuplicateImportError が出ない)
    batch2 = await repo.import_events(
        family_id="f1",
        source_user_id="U1",
        child_id="default",
        raw_text=raw,
        source_filename="day1.txt",
        events=_sample_events(),
    )
    assert batch2.rolled_back_at is None


@pytest.mark.asyncio
async def test_rollback_returns_none_when_no_active_batch(repo: EventRepo) -> None:
    """active な batch がない時 None を返す。"""
    rolled = await repo.rollback_latest_batch(family_id="f1")
    assert rolled is None

    # 1 度 import → rollback → さらに rollback すると None
    await repo.import_events(
        family_id="f1",
        source_user_id="U1",
        child_id="default",
        raw_text="r",
        source_filename=None,
        events=_sample_events(),
    )
    await repo.rollback_latest_batch(family_id="f1")
    rolled2 = await repo.rollback_latest_batch(family_id="f1")
    assert rolled2 is None


@pytest.mark.asyncio
async def test_rollback_only_affects_target_family(repo: EventRepo) -> None:
    """family_id が異なる batch には影響しない。"""
    await repo.import_events(
        family_id="f1",
        source_user_id="U1",
        child_id="default",
        raw_text="raw-f1",
        source_filename=None,
        events=_sample_events(),
    )
    await repo.import_events(
        family_id="f2",
        source_user_id="U2",
        child_id="default",
        raw_text="raw-f2",
        source_filename=None,
        events=_sample_events(),
    )
    rolled = await repo.rollback_latest_batch(family_id="f1")
    assert rolled is not None

    f1_count = await repo.count_events(family_id="f1")
    f2_count = await repo.count_events(family_id="f2")
    assert f1_count == 0
    assert f2_count == 3


@pytest.mark.asyncio
async def test_rollback_picks_most_recent_batch_when_multiple_active(
    repo: EventRepo,
) -> None:
    """複数 active batch があるとき imported_at 最大のものが選ばれる。"""
    b1 = await repo.import_events(
        family_id="f1",
        source_user_id="U1",
        child_id="default",
        raw_text="r1",
        source_filename="d1.txt",
        events=_sample_events("2026-04-25"),
    )
    # 2 件目を入れて imported_at の差を作る
    await asyncio.sleep(0.01)
    b2 = await repo.import_events(
        family_id="f1",
        source_user_id="U1",
        child_id="default",
        raw_text="r2",
        source_filename="d2.txt",
        events=_sample_events("2026-04-26"),
    )
    rolled = await repo.rollback_latest_batch(family_id="f1")
    assert rolled is not None
    assert rolled.batch_id == b2.batch_id
    # b1 は active のまま
    after = await repo.count_events(family_id="f1")
    assert after == 3  # b1 の 3 件のみ残る
    _ = b1
