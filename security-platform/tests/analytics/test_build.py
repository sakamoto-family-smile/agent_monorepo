"""分析 DB の組み立て (dbt の起動と差し替え) のテスト。dbt 本体は偽物に差し替える。"""
from __future__ import annotations

import subprocess

import pytest

from src.analytics import build as build_mod
from src.common.paths import DataPaths


@pytest.fixture
def paths(tmp_path) -> DataPaths:
    return DataPaths(tmp_path / "data")


def fake_dbt(monkeypatch, *, fail: bool = False) -> list[dict]:
    calls: list[dict] = []

    def run(cmd, env, check):
        calls.append({"cmd": cmd, "env": env})
        target = env["SEC_DUCKDB_PATH"]
        with open(target, "ab") as f:
            f.write(b"x")
        if fail:
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(build_mod.subprocess, "run", run)
    monkeypatch.setattr(build_mod, "_dbt_executable", lambda: "dbt")
    return calls


def test_build_swaps_file_and_carries_previous_contents(monkeypatch, paths):
    calls = fake_dbt(monkeypatch)
    assert build_mod.last_success(paths) is None
    out = build_mod.build(paths)
    assert out == paths.duckdb_path and out.read_bytes() == b"x"
    build_mod.build(paths)
    assert out.read_bytes() == b"xx"  # 前回の内容 (スナップショット) を引き継ぐ
    assert not list(paths.root.glob(f"{build_mod.BUILD_PREFIX}*"))
    assert calls[0]["env"]["SEC_DATA_DIR"] == str(paths.root)
    assert calls[0]["cmd"][1] == "build"
    assert build_mod.last_success(paths) is not None
    for name in ("intel", "detection", "remediation"):  # ATTACH 先が必ずある
        assert paths.sqlite_path(name).exists()


def test_failed_build_keeps_previous_database(monkeypatch, paths):
    fake_dbt(monkeypatch)
    build_mod.build(paths)
    fake_dbt(monkeypatch, fail=True)
    with pytest.raises(subprocess.CalledProcessError):
        build_mod.build(paths)
    assert paths.duckdb_path.read_bytes() == b"x"
    assert not list(paths.root.glob(f"{build_mod.BUILD_PREFIX}*"))


def test_snapshots_wait_for_intel_bootstrap(monkeypatch, paths):
    calls = fake_dbt(monkeypatch)
    build_mod.build(paths)
    assert calls[-1]["cmd"][-2:] == build_mod.SKIP_SNAPSHOTS
    import sqlite3

    con = sqlite3.connect(paths.sqlite_path("intel"))
    con.execute("INSERT INTO meta (key, value) VALUES ('bootstrap_completed_at', '2026-10-25T00:00:00Z')")
    con.commit()
    con.close()
    build_mod.build(paths)
    assert "resource_type:snapshot+" not in calls[-1]["cmd"]


def test_concurrent_build_is_refused(monkeypatch, paths):
    from src.common.lock import WriterBusy, writer_lock

    fake_dbt(monkeypatch)
    with writer_lock(paths.root, "analytics"), pytest.raises(WriterBusy):
        build_mod.build(paths)
