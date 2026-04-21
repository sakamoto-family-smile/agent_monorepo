from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from analytics_platform.observability.sinks.file_sink import RotatingFileSink


def _mk_line(event_type: str, ts: datetime | None = None) -> str:
    return json.dumps(
        {
            "event_id": "e1",
            "event_type": event_type,
            "event_timestamp": (ts or datetime.now(UTC)).isoformat(),
        }
    )


async def test_write_creates_hive_partitioned_file(tmp_path: Path) -> None:
    sink = RotatingFileSink(root_dir=tmp_path, service_name="svc")
    ts = datetime(2026, 4, 20, 10, 30, tzinfo=UTC)
    line = _mk_line("llm_call", ts)
    await sink.write_batch([line])

    expected = (
        tmp_path
        / "service_name=svc"
        / "event_type=llm_call"
        / "dt=2026-04-20"
        / "hour=10"
        / "svc_llm_call_2026-04-20_10.jsonl"
    )
    assert expected.exists()
    content = expected.read_text()
    assert content.endswith("\n")
    assert json.loads(content.splitlines()[0])["event_type"] == "llm_call"


async def test_write_groups_by_event_type(tmp_path: Path) -> None:
    sink = RotatingFileSink(root_dir=tmp_path, service_name="svc")
    ts = datetime(2026, 4, 20, 10, 30, tzinfo=UTC)
    await sink.write_batch(
        [_mk_line("llm_call", ts), _mk_line("message", ts), _mk_line("llm_call", ts)]
    )
    et_dirs = [p.name for p in (tmp_path / "service_name=svc").iterdir()]
    assert "event_type=llm_call" in et_dirs
    assert "event_type=message" in et_dirs

    llm_file = next((tmp_path / "service_name=svc" / "event_type=llm_call").rglob("*.jsonl"))
    assert llm_file.read_text().count("\n") == 2


async def test_append_to_existing_shard(tmp_path: Path) -> None:
    sink = RotatingFileSink(root_dir=tmp_path, service_name="svc")
    ts = datetime(2026, 4, 20, 10, 30, tzinfo=UTC)
    await sink.write_batch([_mk_line("llm_call", ts)])
    await sink.write_batch([_mk_line("llm_call", ts)])
    jsonls = list(tmp_path.rglob("*.jsonl"))
    assert len(jsonls) == 1
    assert jsonls[0].read_text().count("\n") == 2


async def test_compress_writes_gzip(tmp_path: Path) -> None:
    sink = RotatingFileSink(root_dir=tmp_path, service_name="svc", compress=True)
    ts = datetime(2026, 4, 20, 10, 30, tzinfo=UTC)
    await sink.write_batch([_mk_line("llm_call", ts)])
    gz_files = list(tmp_path.rglob("*.jsonl.gz"))
    assert len(gz_files) == 1
    with gzip.open(gz_files[0], "rb") as f:
        data = f.read().decode("utf-8")
    assert "llm_call" in data


async def test_partition_uses_event_timestamp(tmp_path: Path) -> None:
    """遅延イベントは event_timestamp のパーティションに入る。"""
    sink = RotatingFileSink(root_dir=tmp_path, service_name="svc")
    old_ts = datetime(2025, 1, 1, 3, 0, tzinfo=UTC)
    await sink.write_batch([_mk_line("llm_call", old_ts)])
    assert (
        tmp_path / "service_name=svc" / "event_type=llm_call" / "dt=2025-01-01" / "hour=03"
    ).exists()


@pytest.mark.parametrize("bad", ["{bad", "", "null"])
async def test_unparsable_lines_go_to_unknown(tmp_path: Path, bad: str) -> None:
    sink = RotatingFileSink(root_dir=tmp_path, service_name="svc")
    await sink.write_batch([bad])
    assert list((tmp_path / "service_name=svc" / "event_type=unknown").rglob("*.jsonl"))
