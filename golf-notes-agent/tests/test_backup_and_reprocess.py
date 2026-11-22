"""日次バックアップ・死活監視の ping・原本からの作り直し・外部 SSD へのコピー。"""
from __future__ import annotations

import os
import sqlite3
import subprocess
from datetime import date
from pathlib import Path

import httpx
import pytest

from app import backup, reprocess
from app.scheduler import Scheduler
from tests.conftest import Env
from tests.test_lesson_parser import SAMPLE
from tests.test_modes import press

ROOT = Path(__file__).resolve().parents[1]


def backups(env: Env) -> list[str]:
    return sorted(p.name for p in env.deps.settings.paths.backup.glob("golf-*.db"))


async def test_backup_is_made_once_a_day_after_3am(env: Env):
    await env.send_text("バックアップされるメモ")
    scheduler = Scheduler(env.deps)
    # 10:00 JST (START) → 3 時を過ぎているので今日の分を作る
    await scheduler.tick()
    assert backups(env) == ["golf-20261122.db"]
    copy = sqlite3.connect(env.deps.settings.paths.backup / "golf-20261122.db")
    assert copy.execute("SELECT text FROM memos").fetchone()[0] == "バックアップされるメモ"
    assert copy.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    copy.close()

    mtime = (env.deps.settings.paths.backup / "golf-20261122.db").stat().st_mtime_ns
    await scheduler.tick()
    assert (env.deps.settings.paths.backup / "golf-20261122.db").stat().st_mtime_ns == mtime

    env.clock.advance(hours=16)  # 翌 02:00 JST はまだ
    await scheduler.tick()
    assert backups(env) == ["golf-20261122.db"]
    env.clock.advance(hours=1)  # 03:00 JST
    await scheduler.tick()
    assert backups(env) == ["golf-20261122.db", "golf-20261123.db"]


def test_prune_keeps_generations(tmp_path):
    from app.config import Paths

    paths = Paths(tmp_path)
    paths.ensure()
    for day in range(1, 6):
        (paths.backup / f"golf-202611{day:02d}.db").write_bytes(b"x")
    removed = backup.prune(paths, keep=3)
    assert [p.name for p in removed] == ["golf-20261101.db", "golf-20261102.db"]
    assert sorted(p.name for p in paths.backup.iterdir()) == [
        "golf-20261103.db",
        "golf-20261104.db",
        "golf-20261105.db",
    ]


async def test_backup_failure_pings_fail_and_pushes_once(env: Env, monkeypatch):
    def broken(*_a, **_k):
        raise backup.BackupError("disk full")

    monkeypatch.setattr(backup, "run_backup", broken)
    pings: list[str] = []
    transport = httpx.MockTransport(lambda req: pings.append(str(req.url)) or httpx.Response(200))
    settings = env.deps.settings.__class__(**{**env.deps.settings.__dict__, "healthcheck_ping_url": "https://hc-ping.com/abc"})
    deps = env.deps.__class__(settings=settings, engine=env.deps.engine, line=env.deps.line, clock=env.clock)
    async with httpx.AsyncClient(transport=transport) as http:
        scheduler = Scheduler(deps, http=http)
        await scheduler.tick()
        env.clock.advance(minutes=1)
        await scheduler.tick()
    assert pings == ["https://hc-ping.com/abc/fail", "https://hc-ping.com/abc/fail"]
    assert len(env.line.pushes) == 1
    assert "バックアップに失敗しました" in env.line.pushes[0][1][0]["text"]


async def test_ping_every_five_minutes_when_healthy(env: Env):
    pings: list[str] = []
    transport = httpx.MockTransport(lambda req: pings.append(str(req.url)) or httpx.Response(200))
    settings = env.deps.settings.__class__(**{**env.deps.settings.__dict__, "healthcheck_ping_url": "https://hc-ping.com/abc"})
    deps = env.deps.__class__(settings=settings, engine=env.deps.engine, line=env.deps.line, clock=env.clock)
    async with httpx.AsyncClient(transport=transport) as http:
        scheduler = Scheduler(deps, http=http)
        for _ in range(6):
            await scheduler.tick()
            env.clock.advance(minutes=1)
    assert pings == ["https://hc-ping.com/abc", "https://hc-ping.com/abc"]


async def _sql(env: Env, sql: str) -> None:
    import sqlalchemy as sa

    async with env.deps.engine.begin() as conn:
        await conn.execute(sa.text(sql))


async def test_reprocess_lesson_dry_run_then_apply(env: Env, capsys):
    await press(env, "action=mode&mode=metrics")
    await env.send_text(SAMPLE)
    # 古いパーサが読み違えた状態を作る (キャリーと符号)
    await _sql(env, "UPDATE launch_metrics SET carry_yd = 999, offline_yd = 6.5")
    await _sql(env, "UPDATE lesson_captures SET parser_version = '0'")

    assert reprocess.main(["lesson", "--dry-run"], settings=env.deps.settings) == 0
    out = capsys.readouterr().out
    assert "capture #1: 1 → 1 球" in out and "1 件中 1 件が変わる" in out and "[dry-run]" in out
    assert await env.scalar("SELECT carry_yd FROM launch_metrics") == 999

    assert reprocess.main(["lesson"], settings=env.deps.settings) == 0
    row = (await env.rows("SELECT carry_yd, offline_yd FROM launch_metrics"))[0]
    assert row == {"carry_yd": 131.4, "offline_yd": -6.5}
    assert await env.scalar("SELECT parser_version FROM lesson_captures") == "1"

    assert reprocess.main(["lesson"], settings=env.deps.settings) == 0
    assert "1 件中 0 件が変わる" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("old_status", "old_flagged", "new_flagged", "expected"),
    [
        ("rejected", False, False, "rejected"),
        ("pending", True, False, "confirmed"),
        ("confirmed", False, True, "pending"),
        ("confirmed", True, True, "confirmed"),
        ("pending", True, True, "pending"),
    ],
)
def test_reprocess_status_rules(old_status, old_flagged, new_flagged, expected):
    assert reprocess._next_status(old_status, old_flagged, new_flagged) == expected


async def test_reprocess_raw_imports_and_redispatches(env: Env, capsys):
    # DB を前の日のバックアップに戻した、などで原本だけが残っている状態を作る
    await env.send_text("DB から消えたメモ")
    await _sql(env, "DELETE FROM memos")
    await _sql(env, "DELETE FROM jobs")
    await _sql(env, "DELETE FROM raw_events")
    (env.deps.settings.paths.raw / "2026" / "11" / "broken.json").write_text("{not json")

    assert reprocess.main(["raw", "--dry-run"], settings=env.deps.settings, now=env.clock()) == 0
    out = capsys.readouterr().out
    assert "DB に無い原本 1 件・読めない原本 1 件 [dry-run]" in out and "broken: raw/2026/11/broken.json" in out
    assert reprocess.main(["raw"], settings=env.deps.settings, now=env.clock()) == 0
    assert await env.scalar("SELECT count(*) FROM raw_events") == 1
    assert await env.scalar("SELECT kind FROM jobs WHERE status = 'pending'") == "redispatch"

    await env.run_jobs()
    assert await env.scalar("SELECT text FROM memos") == "DB から消えたメモ"
    assert "（やり直して保存しました）" in env.line.pushes[-1][1][0]["text"]
    assert reprocess.main(["raw"], settings=env.deps.settings) == 0
    assert "DB に無い原本 0 件" in capsys.readouterr().out


def test_offsite_copies_only_backup_raw_and_media(tmp_path):
    data = tmp_path / "data"
    for rel in ("golf.db", "golf.db-wal", "backup/golf-20261122.db", "raw/2026/11/a.json", "media/2026/11/x.mp4"):
        (data / rel).parent.mkdir(parents=True, exist_ok=True)
        (data / rel).write_text(rel)
    (tmp_path / "ssd").mkdir()  # 外部 SSD のマウント先
    dest = tmp_path / "ssd" / "golf-notes"
    env = {**os.environ, "GOLF_DATA_DIR": str(data), "GOLF_OFFSITE_DIR": str(dest)}
    subprocess.run(["bash", str(ROOT / "scripts" / "offsite_backup.sh"), "copy"], env=env, check=True, capture_output=True)
    copied = sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file())
    assert copied == ["backup/golf-20261122.db", "media/2026/11/x.mp4", "raw/2026/11/a.json"]


def test_offsite_fails_when_ssd_is_missing(tmp_path):
    env = {**os.environ, "GOLF_DATA_DIR": str(tmp_path), "GOLF_OFFSITE_DIR": "/Volumes/__no_such_ssd__/golf"}
    proc = subprocess.run(["bash", str(ROOT / "scripts" / "offsite_backup.sh"), "copy"], env=env, capture_output=True, text=True, check=False)
    assert proc.returncode != 0 and "外部 SSD が外れている" in proc.stderr


def test_backup_path_name():
    from app.config import Paths

    assert backup.backup_path(Paths(Path("/d")), date(2026, 1, 2)).name == "golf-20260102.db"
