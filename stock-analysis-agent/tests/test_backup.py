"""SQLite の日次 backup (services.backup, PROPOSAL-0013) のテスト。"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from services import backup

import config

NOW = datetime(2026, 11, 15, 18, 0, tzinfo=UTC)


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "stock_analysis.db"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE reports (id INTEGER PRIMARY KEY, body TEXT)")
    conn.executemany("INSERT INTO reports (body) VALUES (?)", [("a",), ("b",)])
    conn.commit()
    monkeypatch.setattr(config.settings, "database_url", f"sqlite+aiosqlite:///{path}")
    monkeypatch.setattr(config.settings, "backup_dir", str(tmp_path / "backups"))
    monkeypatch.setattr(config.settings, "backup_retention_days", 14)
    yield conn
    conn.close()


async def test_backup_copies_committed_rows_including_wal(db, tmp_path):
    db.execute("INSERT INTO reports (body) VALUES ('c')")
    db.commit()  # WAL に残ったままの行も backup に入る

    dest = await backup.run_backup(NOW)

    assert dest.name == "stock_analysis-20261115-180000.db"
    copy = sqlite3.connect(dest)
    try:
        assert copy.execute("SELECT count(*) FROM reports").fetchone()[0] == 3
    finally:
        copy.close()
    assert not list((tmp_path / "backups").glob("*.tmp"))


async def test_backup_prunes_old_files_but_keeps_latest(db, tmp_path):
    for days in (20, 15, 3):
        await backup.run_backup(NOW - timedelta(days=days))

    await backup.run_backup(NOW)

    names = [p.name for _, p in backup.list_backups(tmp_path / "backups")]
    assert names == ["stock_analysis-20261112-180000.db", "stock_analysis-20261115-180000.db"]


def test_prune_keeps_the_only_backup_even_if_old(tmp_path):
    d = tmp_path / "backups"
    d.mkdir()
    (d / "stock_analysis-20250101-000000.db").write_bytes(b"")

    assert backup.prune_backups(d, retention_days=14, now=NOW) == []


def test_list_backups_ignores_other_files(tmp_path):
    d = tmp_path / "backups"
    d.mkdir()
    (d / "notes.txt").write_text("x")
    (d / "stock_analysis-20261115-180000.db.tmp").write_bytes(b"")

    assert backup.list_backups(d) == []


async def test_backup_requires_sqlite(monkeypatch):
    monkeypatch.setattr(config.settings, "database_url", "postgresql+asyncpg://u:p@h/db")

    with pytest.raises(backup.BackupError, match="SQLite"):
        await backup.run_backup(NOW)


async def test_backup_fails_when_db_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "database_url", f"sqlite+aiosqlite:///{tmp_path / 'none.db'}")
    monkeypatch.setattr(config.settings, "backup_dir", str(tmp_path / "backups"))

    with pytest.raises(backup.BackupError, match="ありません"):
        await backup.run_backup(NOW)
