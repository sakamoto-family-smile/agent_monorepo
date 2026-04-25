"""dbt の cross-DB マクロ + adapter dispatch のスモークテスト。

`dbt parse` は DB 接続を張らずに Jinja を全展開するため、SQL の文法ミスや
マクロのタイポを CI で検出できる。
- local (DuckDB) は常時テスト対象
- gcp (BigQuery) は `dbt-bigquery` が入っている時だけテスト対象
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DBT_DIR = REPO_ROOT / "dbt"


def _has_dbt_bigquery() -> bool:
    return importlib.util.find_spec("dbt.adapters.bigquery") is not None


def _run_dbt_parse(target: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    full_env = os.environ.copy()
    full_env["DBT_PROFILES_DIR"] = str(DBT_DIR)
    full_env["DBT_PROJECT_DIR"] = str(DBT_DIR)
    if env:
        full_env.update(env)
    return subprocess.run(
        ["dbt", "parse", "--profiles-dir", str(DBT_DIR), "--project-dir", str(DBT_DIR), "--target", target],
        capture_output=True,
        text=True,
        env=full_env,
        cwd=DBT_DIR,
        check=False,
    )


@pytest.mark.skipif(shutil.which("dbt") is None, reason="dbt CLI not installed")
def test_dbt_parse_local_target() -> None:
    """DuckDB target で dbt parse が成功する (既存挙動の回帰テスト)。"""
    proc = _run_dbt_parse("local")
    assert proc.returncode == 0, f"dbt parse --target local failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"


@pytest.mark.skipif(
    shutil.which("dbt") is None or not _has_dbt_bigquery(),
    reason="dbt-bigquery not installed (use `uv sync --extra gcp`)",
)
def test_dbt_parse_gcp_target() -> None:
    """BigQuery target で dbt parse が成功する。

    実際の BQ 接続は張らないが、profile 解決のため env を最小限に埋める。
    """
    proc = _run_dbt_parse(
        "gcp",
        env={
            "ANALYTICS_BQ_PROJECT": "test-project",
            "ANALYTICS_BQ_LOCATION": "US",
            "ANALYTICS_BQ_RAW_DATASET": "analytics_raw",
            "ANALYTICS_BQ_STAGING_DATASET": "analytics_staging",
            "ANALYTICS_BQ_MARTS_DATASET": "analytics_marts",
            "ANALYTICS_BQ_DEFAULT_DATASET": "analytics_staging",
            "ANALYTICS_BQ_RAW_TABLE": "agent_events_external",
        },
    )
    assert proc.returncode == 0, f"dbt parse --target gcp failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"


@pytest.mark.skipif(shutil.which("dbt") is None, reason="dbt CLI not installed")
def test_cross_db_macros_present() -> None:
    """マクロファイルが期待通りに存在することを確認する。"""
    macros_dir = DBT_DIR / "macros"
    assert (macros_dir / "cross_db.sql").exists()
    assert (macros_dir / "generate_schema_name.sql").exists()
    body = (macros_dir / "cross_db.sql").read_text()
    for macro in ("star_except", "quantile_cont", "epoch_seconds_diff", "parse_event_timestamp", "date_from_timestamp"):
        assert f"macro {macro}" in body, f"macro {macro} not defined in cross_db.sql"
