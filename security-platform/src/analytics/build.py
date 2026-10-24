"""分析 DB (data/security.duckdb) の組み立て。

dbt は一時ファイル ``security_build.duckdb`` に対して実行し、成功したら置き換える。
(DuckDB のカタログ名はファイル名から決まるため、一時ファイルも ``.duckdb`` で終える)
UI などで security.duckdb を開いたままでも更新が止まらないようにするため。
スナップショット (履歴) を引き継ぐため、一時ファイルは前回の security.duckdb のコピーから始める。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess  # nosec B404 - 固定引数で dbt を起動するだけ
import sys
from datetime import UTC, datetime
from pathlib import Path

from ..common.migrate import upgrade
from ..common.paths import DB_NAMES, DataPaths

logger = logging.getLogger(__name__)

DBT_DIR = Path(__file__).resolve().parents[2] / "dbt"
SUCCESS_MARKER = ".analytics_last_success"
BUILD_FILE = "security_build.duckdb"


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


def build(paths: DataPaths, extra_args: list[str] | None = None) -> Path:
    """dbt build を実行して security.duckdb を差し替え、そのパスを返す。"""
    # ATTACH 先の SQLite ファイルが無ければ作る。既存ファイルには触らない (書き込みは各サービスだけ)
    for name in DB_NAMES:
        if not paths.sqlite_path(name).exists():
            upgrade(name, paths)
    final = paths.duckdb_path
    tmp = final.with_name(BUILD_FILE)
    _remove(tmp)
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
