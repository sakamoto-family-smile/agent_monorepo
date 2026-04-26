"""EventRepo (SQLite) テスト。

- 冪等 UPSERT: 同じファイル再送で件数増えない
- 異なるファイルは重複しない
- raw_text_hash 同一は DuplicateImportError
- date range クエリ
"""

from __future__ import annotations

import pytest
from conftest import load_fixture
from parser.piyolog_parser import parse_piyolog_text
from repositories.event_repo import DuplicateImportError, EventRepo


@pytest.fixture
async def repo(tmp_path):
    """各テスト用に独立した SQLite ファイル DB を立てる。"""
    db_path = str(tmp_path / "test.db")
    r = EventRepo(database_url=f"sqlite+aiosqlite:///{db_path}")
    await r.initialize()
    try:
        yield r
    finally:
        await r.dispose()


@pytest.mark.asyncio
async def test_import_single_file_stores_events(repo: EventRepo):
    text = load_fixture("daily_sample.txt")
    events = parse_piyolog_text(text).days[0].events
    batch = await repo.import_events(
        family_id="fam1",
        source_user_id="Utest1",
        child_id="default",
        raw_text=text,
        source_filename="daily_sample.txt",
        events=events,
    )
    assert batch.event_count == len(events)
    count = await repo.count_events(family_id="fam1")
    assert count == len(events)


@pytest.mark.asyncio
async def test_duplicate_raw_text_raises(repo: EventRepo):
    text = load_fixture("daily_sample.txt")
    events = parse_piyolog_text(text).days[0].events
    await repo.import_events(
        family_id="fam1",
        source_user_id="Utest1",
        child_id="default",
        raw_text=text,
        source_filename="daily_sample.txt",
        events=events,
    )
    with pytest.raises(DuplicateImportError):
        await repo.import_events(
            family_id="fam1",
            source_user_id="Utest1",
            child_id="default",
            raw_text=text,
            source_filename="daily_sample.txt",
            events=events,
        )


@pytest.mark.asyncio
async def test_different_families_can_import_same_raw(repo: EventRepo):
    """family_id が違えば同じ raw を重複検知しない。"""
    text = load_fixture("daily_sample.txt")
    events = parse_piyolog_text(text).days[0].events
    await repo.import_events(
        family_id="famA",
        source_user_id="Utest1",
        child_id="default",
        raw_text=text,
        source_filename=None,
        events=events,
    )
    # famB は別 family なので OK
    await repo.import_events(
        family_id="famB",
        source_user_id="Utest2",
        child_id="default",
        raw_text=text,
        source_filename=None,
        events=events,
    )
    assert await repo.count_events(family_id="famA") == len(events)
    assert await repo.count_events(family_id="famB") == len(events)


@pytest.mark.asyncio
async def test_different_raw_text_imports_independently(repo: EventRepo):
    d = load_fixture("daily_sample.txt")
    m = load_fixture("monthly_sample.txt")
    d_events = parse_piyolog_text(d).days[0].events
    m_parsed = parse_piyolog_text(m)
    m_events = [e for day in m_parsed.days for e in day.events]
    await repo.import_events(
        family_id="fam1",
        source_user_id="Utest1",
        child_id="default",
        raw_text=d,
        source_filename="daily",
        events=d_events,
    )
    await repo.import_events(
        family_id="fam1",
        source_user_id="Utest1",
        child_id="default",
        raw_text=m,
        source_filename="monthly",
        events=m_events,
    )
    total = await repo.count_events(family_id="fam1")
    assert total == len(d_events) + len(m_events)


@pytest.mark.asyncio
async def test_fetch_events_in_range_returns_expected(repo: EventRepo):
    text = load_fixture("monthly_sample.txt")
    events = [e for day in parse_piyolog_text(text).days for e in day.events]
    await repo.import_events(
        family_id="fam1",
        source_user_id="Utest1",
        child_id="default",
        raw_text=text,
        source_filename=None,
        events=events,
    )
    rows22 = await repo.fetch_events_in_range(
        family_id="fam1", date_from="2026-04-22", date_to="2026-04-22"
    )
    rows23 = await repo.fetch_events_in_range(
        family_id="fam1", date_from="2026-04-23", date_to="2026-04-23"
    )
    rows_both = await repo.fetch_events_in_range(
        family_id="fam1", date_from="2026-04-22", date_to="2026-04-23"
    )
    assert len(rows22) == 6   # monthly_sample の 4/22 は 6 event
    assert len(rows23) == 7   # monthly_sample の 4/23 は 7 event
    assert len(rows_both) == len(rows22) + len(rows23)
