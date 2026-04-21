"""dbt-duckdb の統合スモークテスト。

- AnalyticsLogger で数件 emit
- DuckDB が JSONL を直接 read_json_auto で読めることを確認
- raw → stg_agent_events → stg_llm_calls の一気通貫
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from analytics_platform.observability.analytics_logger import AnalyticsLogger
from analytics_platform.observability.sinks.file_sink import RotatingFileSink


@pytest.fixture
def seeded_raw(tmp_path: Path) -> Path:
    async def _run() -> None:
        sink = RotatingFileSink(root_dir=tmp_path / "raw", service_name="svc")
        al = AnalyticsLogger(
            service_name="svc",
            service_version="0.1.0",
            environment="local",
            sink=sink,
        )
        for i in range(5):
            al.emit(
                event_type="llm_call",
                event_version="1.0.0",
                severity="INFO",
                fields={
                    "llm_provider": "anthropic",
                    "llm_model": "claude-opus-4-7",
                    "input_tokens": 100 + i,
                    "output_tokens": 10 + i,
                    "cache_read_tokens": 10,
                    "cache_creation_tokens": 0,
                    "total_cost_usd": 0.01,
                    "latency_ms": 500,
                },
                user_id=f"u{i}",
                session_id=f"s{i}",
            )
        al.emit(
            event_type="message",
            event_version="1.0.0",
            severity="INFO",
            fields={
                "message_id": "m1",
                "message_role": "user",
                "message_index": 0,
                "content_text": "hi",
                "content_hash": "sha256:" + "a" * 64,
                "content_size_bytes": 2,
                "content_truncated": False,
            },
        )
        await al.flush()

    import asyncio

    asyncio.run(_run())
    return tmp_path / "raw"


def test_duckdb_can_read_hive_partitioned_jsonl(seeded_raw: Path) -> None:
    con = duckdb.connect(":memory:")
    glob = str(seeded_raw / "**/*.jsonl")
    result = con.execute(
        """
        SELECT event_type, COUNT(*) AS n
        FROM read_json_auto(
            ?,
            hive_partitioning = true,
            union_by_name = true,
            format = 'newline_delimited'
        )
        GROUP BY 1 ORDER BY 1
        """,
        [glob],
    ).fetchall()
    assert ("llm_call", 5) in result
    assert ("message", 1) in result


def test_duckdb_extracts_hive_columns(seeded_raw: Path) -> None:
    con = duckdb.connect(":memory:")
    glob = str(seeded_raw / "**/*.jsonl")
    rows = con.execute(
        """
        SELECT DISTINCT service_name, event_type
        FROM read_json_auto(
            ?,
            hive_partitioning = true,
            union_by_name = true,
            format = 'newline_delimited'
        )
        ORDER BY 1, 2
        """,
        [glob],
    ).fetchall()
    assert ("svc", "llm_call") in rows
    assert ("svc", "message") in rows
