"""分析 DB (data/security.duckdb) の組み立て。

dbt は一時ファイル ``security_build_<ランダム>.duckdb`` に対して実行し、成功したら置き換える。
(DuckDB のカタログ名はファイル名から決まるため、一時ファイルも ``.duckdb`` で終える)
UI などで security.duckdb を開いたままでも更新が止まらないようにするため。
スナップショット (履歴) を引き継ぐため、一時ファイルは前回の security.duckdb のコピーから始める。
同時に 2 つ走らないよう data/.locks/analytics.lock を取る。

intel のブートストラップが終わるまではスナップショット (とその下流) を実行しない。
取り込み途中の状態を「変化」として履歴に残さないため。
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import subprocess  # nosec B404 - 固定引数で dbt を起動するだけ
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from ..common.lock import writer_lock
from ..common.migrate import upgrade
from ..common.paths import DB_NAMES, DataPaths

logger = logging.getLogger(__name__)

DBT_DIR = Path(__file__).resolve().parents[2] / "dbt"
SUCCESS_MARKER = ".analytics_last_success"
BUILD_PREFIX = "security_build_"
SKIP_SNAPSHOTS = ["--exclude", "resource_type:snapshot+"]


def _dbt_executable() -> str:
    local = Path(sys.executable).parent / "dbt"
    found = str(local) if local.exists() else shutil.which("dbt")
    if not found:
        raise FileNotFoundError("dbt executable not found (uv sync で dbt-duckdb を入れてください)")
    return found


def _remove(path: Path) -> None:
    for p in (path, path.with_name(path.name + ".wal")):
        if p.exists():
            p.unlink()


def last_success(paths: DataPaths) -> datetime | None:
    marker = paths.root / SUCCESS_MARKER
    if not marker.exists():
        return None
    return datetime.fromtimestamp(marker.stat().st_mtime, tz=UTC)


def intel_bootstrapped(paths: DataPaths) -> bool:
    path = paths.sqlite_path("intel")
    if not path.exists():
        return False
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT value FROM meta WHERE key = 'bootstrap_completed_at'").fetchone()
    except sqlite3.OperationalError:
        return False
    finally:
        con.close()
    return row is not None


def build(paths: DataPaths, extra_args: list[str] | None = None) -> Path:
    """dbt build を実行して security.duckdb を差し替え、そのパスを返す。"""
    with writer_lock(paths.root, "analytics"):
        return _build(paths, extra_args)


def _build(paths: DataPaths, extra_args: list[str] | None) -> Path:
    # ATTACH 先の SQLite ファイルが無ければ作る。既存ファイルには触らない (書き込みは各サービスだけ)
    for name in DB_NAMES:
        if not paths.sqlite_path(name).exists():
            upgrade(name, paths)
    final = paths.duckdb_path
    for stale in final.parent.glob(f"{BUILD_PREFIX}*.duckdb*"):  # 前回途中で落ちた分
        stale.unlink()
    tmp = final.with_name(f"{BUILD_PREFIX}{uuid.uuid4().hex[:12]}.duckdb")
    if final.exists():
        shutil.copy2(final, tmp)
    work = paths.root / ".dbt"
    env = {**os.environ, "SEC_DUCKDB_PATH": str(tmp), "SEC_DATA_DIR": str(paths.root)}
    cmd = [
        _dbt_executable(), "build",
        "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR),
        "--target-path", str(work / "target"), "--log-path", str(work / "logs"),
        *(extra_args or []),
    ]
    if not intel_bootstrapped(paths):
        logger.info("intel bootstrap in progress; skipping snapshots")
        cmd += SKIP_SNAPSHOTS
    logger.info("running: %s", " ".join(cmd))
    try:
        subprocess.run(cmd, env=env, check=True)  # nosec B603
    except subprocess.CalledProcessError:
        _remove(tmp)
        raise
    os.replace(tmp, final)
    (paths.root / SUCCESS_MARKER).touch()
    logger.info("analytics database updated: %s", final)
    return final
