"""SQLite の日次 backup (PROPOSAL-0013 §4.4)。

backend のプロセス内から SQLite のオンライン backup API でコピーを取るので、書き込み中でも
整合した状態のファイルになる (ホストから DB ファイルを直接コピーしない)。
`<backup_dir>/stock_analysis-YYYYMMDD-HHMMSS.db` に保存し、保持日数を過ぎたものを消す。
外部ディスクへのコピーはホストの launchd (scripts/local/offsite_backup_launchd.sh) が行う。
"""

from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import config

logger = logging.getLogger(__name__)

BACKUP_PREFIX = "stock_analysis-"
_NAME_RE = re.compile(rf"^{BACKUP_PREFIX}(\d{{8}}-\d{{6}})\.db$")
_STAMP_FORMAT = "%Y%m%d-%H%M%S"


class BackupError(RuntimeError):
    pass


def sqlite_path_from_url(url: str) -> Path:
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            return Path(url.removeprefix(prefix))
    raise BackupError("backup は SQLite のときだけ使えます (GCP の Cloud SQL は自動 backup を使う)")


def list_backups(backup_dir: Path) -> list[tuple[datetime, Path]]:
    """backup ファイルを古い順に返す。"""
    if not backup_dir.is_dir():
        return []
    found = []
    for path in backup_dir.iterdir():
        m = _NAME_RE.match(path.name)
        if m:
            stamp = datetime.strptime(m.group(1), _STAMP_FORMAT).replace(tzinfo=UTC)
            found.append((stamp, path))
    return sorted(found)


def _backup_sync(db_path: Path, backup_dir: Path, now: datetime) -> Path:
    if not db_path.exists():
        raise BackupError(f"DB ファイルがありません: {db_path}")
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"{BACKUP_PREFIX}{now.strftime(_STAMP_FORMAT)}.db"
    tmp = dest.with_suffix(".db.tmp")
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        out = sqlite3.connect(tmp)
        try:
            src.backup(out)
            ok = out.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            out.close()
    finally:
        src.close()
    if ok != "ok":
        tmp.unlink(missing_ok=True)
        raise BackupError(f"backup の integrity_check に失敗しました: {ok}")
    tmp.replace(dest)
    return dest


def prune_backups(backup_dir: Path, *, retention_days: int, now: datetime) -> list[Path]:
    """保持日数を過ぎた backup を消す。最新の 1 件は日数に関わらず残す。"""
    backups = list_backups(backup_dir)
    cutoff = now - timedelta(days=retention_days)
    removed = []
    for stamp, path in backups[:-1]:
        if stamp < cutoff:
            path.unlink(missing_ok=True)
            removed.append(path)
    return removed


async def run_backup(now: datetime | None = None) -> Path:
    s = config.settings
    now = now or datetime.now(UTC)
    db_path = sqlite_path_from_url(s.resolved_database_url)
    backup_dir = Path(s.backup_dir)
    dest = await asyncio.to_thread(_backup_sync, db_path, backup_dir, now)
    removed = await asyncio.to_thread(
        prune_backups, backup_dir, retention_days=s.backup_retention_days, now=now
    )
    logger.info("backup saved: %s (removed %d old backups)", dest.name, len(removed))
    return dest


__all__ = ["BackupError", "list_backups", "prune_backups", "run_backup", "sqlite_path_from_url"]
