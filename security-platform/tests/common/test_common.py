"""common/ (DB 接続・マイグレーション・イベント・生データ・スケジューラ) のテスト。"""
from __future__ import annotations

import stat
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from src.common.db import make_engine
from src.common.events import Consumer, Outbox
from src.common.migrate import upgrade_all
from src.common.paths import DataPaths
from src.common.raw_store import RawStore
from src.common.scheduler import Job, Scheduler, due_jobs, seconds_until_next
from src.common.timeutil import parse_iso, to_iso


@pytest.fixture
def paths(tmp_path) -> DataPaths:
    p = DataPaths(tmp_path / "data")
    upgrade_all(p)
    return p


def test_migrations_create_three_databases_in_wal_mode(paths):
    for name in ("intel", "detection", "remediation"):
        engine = make_engine(paths.sqlite_path(name))
        with engine.connect() as conn:
            assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
            tables = set(conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).scalars())
        assert {"events"} <= tables


def test_read_only_engine_rejects_writes(paths):
    ro = make_engine(paths.sqlite_path("intel"), read_only=True)
    with pytest.raises(OperationalError), ro.begin() as conn:
        conn.execute(text("INSERT INTO meta (key, value) VALUES ('x', 'y')"))


def test_read_only_engine_requires_existing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        make_engine(tmp_path / "missing.db", read_only=True)


def test_outbox_writes_db_and_jsonl_and_consumer_tracks_cursor(paths):
    intel = make_engine(paths.sqlite_path("intel"))
    outbox = Outbox(paths.events_dir, "intel")
    with intel.begin() as conn:
        outbox.publish(conn, "advisory.changed", {"advisory_id": "CVE-2026-0001"})
        outbox.publish(conn, "advisory.changed", {"advisory_id": "CVE-2026-0002"})
    assert outbox.flush() == 2
    jsonl = list(paths.events_dir.glob("type=advisory.changed/dt=*/intel.jsonl"))
    assert len(jsonl) == 1 and len(jsonl[0].read_text().splitlines()) == 2

    consumer = Consumer(
        make_engine(paths.sqlite_path("intel"), read_only=True),
        make_engine(paths.sqlite_path("detection")),
        "intel",
    )
    first = consumer.fetch(limit=1)
    assert [e.payload["advisory_id"] for e in first] == ["CVE-2026-0001"]
    consumer.ack(first[0].seq)
    rest = consumer.fetch()
    assert [e.payload["advisory_id"] for e in rest] == ["CVE-2026-0002"]
    consumer.ack(first[0].seq)  # 後退はしない
    assert consumer.last_seq() == first[0].seq


def test_outbox_discard_drops_pending(paths):
    outbox = Outbox(paths.events_dir, "intel")
    with make_engine(paths.sqlite_path("intel")).connect() as conn:
        outbox.publish(conn, "x", {})
    outbox.discard()
    assert outbox.flush() == 0


def test_raw_store_writes_read_only_and_refuses_overwrite(tmp_path):
    store = RawStore(tmp_path / "raw")
    path = store.write_bytes("kev", "a.json", b"{}")
    assert path.read_bytes() == b"{}"
    assert not path.stat().st_mode & stat.S_IWUSR
    with pytest.raises(FileExistsError):
        store.write_bytes("kev", "a.json", b"{}")
    assert store.relative(path).startswith("raw/kev/dt=")


def test_raw_store_prune_keeps_newest(tmp_path):
    store = RawStore(tmp_path / "raw")
    for day, run in [("2026-10-01", "a"), ("2026-10-02", "b"), ("2026-10-03", "c")]:
        p = store.path_for("osv", f"full-{run}/PyPI.zip", day=day)
        p.parent.mkdir(parents=True)
        p.write_bytes(b"z")
        p.chmod(0o444)
    removed = store.prune_dirs("osv", "full-", keep=2)
    assert [r.name for r in removed] == ["full-a"]
    assert len(list((tmp_path / "raw/osv").glob("dt=*/full-*"))) == 2


def test_parse_iso_accepts_nanoseconds():
    dt = parse_iso("2026-10-23T22:45:03.452878321Z")
    assert dt == datetime(2026, 10, 23, 22, 45, 3, 452878, tzinfo=UTC)
    assert to_iso(dt) == "2026-10-23T22:45:03.452878Z"


def test_due_jobs_and_wait():
    now = datetime(2026, 10, 24, tzinfo=UTC)
    jobs = [Job("a", timedelta(hours=1), lambda: None), Job("b", timedelta(hours=1), lambda: None)]
    last = {"a": now - timedelta(minutes=10), "b": None}
    assert [j.name for j in due_jobs(jobs, last.get, now)] == ["b"]
    last["b"] = now - timedelta(minutes=30)
    assert seconds_until_next(jobs, last.get, now) == pytest.approx(30 * 60)


def test_scheduler_isolates_failures_and_backs_off():
    calls: list[str] = []

    def boom() -> None:
        calls.append("boom")
        raise RuntimeError("x")

    sched = Scheduler(
        [Job("bad", timedelta(hours=1), boom), Job("good", timedelta(hours=1), lambda: calls.append("good"))],
        lambda _name: None,
    )
    assert sched.run_once() == ["bad", "good"]
    # 失敗直後の bad は retry_after まで再実行しない。good は last_success が None のまま
    assert sched.run_once() == ["good"]
    assert calls == ["boom", "good", "good"]


def test_raw_store_prune_counts_a_run_spanning_days_once(tmp_path):
    import os

    store = RawStore(tmp_path / "raw")
    layout = [("2026-10-01", "full-old", 1), ("2026-10-02", "full-new", 2), ("2026-10-03", "full-new", 3)]
    for day, run, mtime in layout:
        p = store.path_for("osv", f"{run}/PyPI.zip", day=day)
        p.parent.mkdir(parents=True)
        p.write_bytes(b"z")
        os.utime(p.parent, (mtime, mtime))
    removed = store.prune_dirs("osv", "full-", keep=1)
    assert [r.name for r in removed] == ["full-old"]
