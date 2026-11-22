"""golf.db の日次バックアップ (コンテナの中で SQLite の backup API を使う)。

data/backup/golf-YYYYMMDD.db に作り、整合性を確かめてから置く。BACKUP_KEEP 世代を残す。
ホストの launchd (scripts/offsite_backup.sh) は、この出力と raw/・media/ だけを外部 SSD にコピーする
(書き込み中の golf.db はコピーしない)。
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path

from app.config import Paths, Settings

logger = logging.getLogger(__name__)

PREFIX = "golf-"
SUFFIX = ".db"


class BackupError(Exception):
    pass


def backup_path(paths: Paths, day: date) -> Path:
    return paths.backup / f"{PREFIX}{day:%Y%m%d}{SUFFIX}"


def run_backup(paths: Paths, day: date, keep: int) -> Path:
    """同期処理 (asyncio.to_thread で呼ぶ)。作ったファイルを返す。"""
    paths.backup.mkdir(parents=True, exist_ok=True)
    dest = backup_path(paths, day)
    tmp = dest.with_suffix(".db.part")
    tmp.unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{paths.db}?mode=ro", uri=True)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
        result = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise BackupError(f"integrity_check: {result}")
        # バックアップは単体で開けるよう WAL にしない
        dst.execute("PRAGMA journal_mode=DELETE")
    finally:
        dst.close()
        src.close()
    try:
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    prune(paths, keep)
    logger.info("backup written: %s (%d bytes)", dest.name, dest.stat().st_size)
    return dest


def prune(paths: Paths, keep: int) -> list[Path]:
    files = sorted(paths.backup.glob(f"{PREFIX}*{SUFFIX}"))
    removed = files[:-keep] if keep > 0 else []
    for path in removed:
        path.unlink()
    return removed


def main() -> None:
    """今日の分を今すぐ作る (make backup-now)。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.from_env()
    today = datetime.now(settings.tz).date()
    print(run_backup(settings.paths, today, settings.backup_keep))


if __name__ == "__main__":
    main()
