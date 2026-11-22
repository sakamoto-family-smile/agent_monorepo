"""push の上限・仮のセッション・開いているセッションの自動終了・マイグレーション。"""
from __future__ import annotations

from datetime import timedelta

import sqlalchemy as sa

from app.push import push_text
from app.storage import sessions
from app.storage.tables import sessions as sessions_table
from app.timeutil import iso
from tests.conftest import ME, Env


async def test_push_stops_at_monthly_limit_except_essential(tmp_path):
    from app.main import close_deps, open_deps
    from tests.conftest import FakeClock, FakeLine, make_settings

    line = FakeLine()
    deps = await open_deps(make_settings(tmp_path, push_monthly_limit=2), line, FakeClock())
    try:
        assert await push_text(deps, to=ME, kind="ocr", key="a", body="1")
        assert await push_text(deps, to=ME, kind="ocr", key="b", body="2")
        assert not await push_text(deps, to=ME, kind="ocr", key="c", body="3")
        assert await push_text(deps, to=ME, kind="failure", key="d", body="4")
    finally:
        await close_deps(deps)
    assert [m[0]["text"] for _, m, _ in line.pushes] == ["1", "2", "4"]
    # 同じ key は同じ X-Line-Retry-Key になる (LINE 側で二重送信を防ぐ)
    assert len({k for _, _, k in line.pushes}) == 3


async def test_push_count_resets_each_month(tmp_path):
    from app.main import close_deps, open_deps
    from tests.conftest import FakeClock, FakeLine, make_settings

    clock = FakeClock()
    deps = await open_deps(make_settings(tmp_path, push_monthly_limit=1), FakeLine(), clock)
    try:
        assert await push_text(deps, to=ME, kind="ocr", key="a", body="1")
        assert not await push_text(deps, to=ME, kind="ocr", key="b", body="2")
        clock.advance(days=10)  # 12/02 JST
        assert await push_text(deps, to=ME, kind="ocr", key="c", body="3")
    finally:
        await close_deps(deps)


async def test_items_on_the_same_day_share_a_provisional_session(env: Env):
    await env.send_text("朝のメモ")
    env.clock.advance(hours=10)  # 20:00 JST
    await env.send_text("夜のメモ")
    env.clock.advance(hours=5)  # 翌 01:00 JST
    reply = await env.send_text("日付が変わった")

    assert reply.endswith("11/23 の練習（仮）")
    assert [r["session_id"] for r in await env.rows("SELECT session_id FROM memos ORDER BY id")] == [1, 1, 2]


async def _open(env: Env, kind: str = "lesson") -> int:
    now = env.clock()
    async with env.deps.engine.begin() as conn:
        res = await conn.execute(
            sa.insert(sessions_table).values(
                kind=kind, date="2026-11-22", provisional=False, started_at=iso(now), last_activity_at=iso(now)
            )
        )
        return int(res.inserted_primary_key[0])


async def test_items_go_to_the_open_session_across_midnight(env: Env):
    sid = await _open(env, "practice")
    env.clock.advance(hours=14, minutes=30)  # 00:30 JST 翌日。最終操作から 6 時間以内に操作し続ける
    async with env.deps.engine.begin() as conn:
        await sessions.touch(conn, sid, env.clock() - timedelta(hours=1))
    reply = await env.send_text("0 時をまたいでも同じ練習")
    assert reply.endswith("11/22 の練習")
    assert await env.scalar("SELECT session_id FROM memos") == sid


async def test_open_session_ends_after_six_idle_hours(env: Env):
    sid = await _open(env)
    env.clock.advance(hours=6)
    reply = await env.send_text("6 時間後のメモ")
    assert reply.endswith("11/22 の練習（仮）")
    row = (await env.rows("SELECT ended_at, end_reason, started_at FROM sessions WHERE id = :id", id=sid))[0]
    assert row["end_reason"] == "idle" and row["ended_at"] == row["started_at"]


async def test_migrations_create_all_tables(env: Env):
    names = {r["name"] for r in await env.rows("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"raw_events", "jobs", "push_log", "courses", "sessions", "memos", "media"} <= names
    assert await env.scalar("PRAGMA journal_mode") == "wal"
