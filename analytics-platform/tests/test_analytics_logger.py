from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from observability.analytics_logger import AnalyticsLogger
from observability.sinks.file_sink import RotatingFileSink
from pydantic import ValidationError


@dataclass
class _MemorySink:
    written: list[list[str]] = field(default_factory=list)
    fail_once: bool = False

    async def write_batch(self, lines: list[str]) -> None:
        if self.fail_once:
            self.fail_once = False
            raise OSError("simulated sink failure")
        self.written.append(lines)


def _new_logger(sink) -> AnalyticsLogger:
    return AnalyticsLogger(
        service_name="svc",
        service_version="0.1.0",
        environment="local",
        sink=sink,
    )


def test_emit_validates_and_enqueues() -> None:
    sink = _MemorySink()
    logger = _new_logger(sink)
    eid = logger.emit(
        event_type="llm_call",
        event_version="1.0.0",
        severity="INFO",
        fields={
            "llm_provider": "anthropic",
            "llm_model": "claude-opus-4-7",
            "input_tokens": 100,
            "output_tokens": 10,
        },
    )
    assert eid
    assert logger.buffer_size == 1


def test_emit_rejects_invalid_event() -> None:
    sink = _MemorySink()
    logger = _new_logger(sink)
    with pytest.raises(ValidationError):
        logger.emit(
            event_type="llm_call",
            event_version="1.0.0",
            severity="INFO",
            fields={"llm_provider": "anthropic"},  # missing required fields
        )
    assert logger.buffer_size == 0


async def test_flush_writes_all_and_clears_buffer() -> None:
    sink = _MemorySink()
    logger = _new_logger(sink)
    for _ in range(3):
        logger.emit(
            event_type="business_event",
            event_version="1.0.0",
            severity="INFO",
            fields={"business_domain": "demo", "action": "a"},
        )
    n = await logger.flush()
    assert n == 3
    assert logger.buffer_size == 0
    assert sum(len(b) for b in sink.written) == 3


async def test_flush_failure_returns_to_buffer() -> None:
    sink = _MemorySink(fail_once=True)
    logger = _new_logger(sink)
    logger.emit(
        event_type="business_event",
        event_version="1.0.0",
        severity="INFO",
        fields={"business_domain": "demo", "action": "a"},
    )
    with pytest.raises(IOError):
        await logger.flush()
    # イベントはバッファに戻っている
    assert logger.buffer_size == 1
    # 次の flush は成功する
    n = await logger.flush()
    assert n == 1
    assert logger.buffer_size == 0


async def test_roundtrip_with_real_file_sink(tmp_path: Path) -> None:
    sink = RotatingFileSink(root_dir=tmp_path, service_name="svc")
    logger = _new_logger(sink)
    logger.emit(
        event_type="llm_call",
        event_version="1.0.0",
        severity="INFO",
        fields={
            "llm_provider": "anthropic",
            "llm_model": "m",
            "input_tokens": 1,
            "output_tokens": 1,
        },
    )
    await logger.flush()
    jsonls = list(tmp_path.rglob("*.jsonl"))
    assert len(jsonls) == 1
    parsed = json.loads(jsonls[0].read_text().splitlines()[0])
    assert parsed["event_type"] == "llm_call"
    assert parsed["service_name"] == "svc"
    assert parsed["event_id"]


def test_buffer_overflow_drops_oldest() -> None:
    sink = _MemorySink()
    logger = AnalyticsLogger(
        service_name="svc",
        service_version="0.1.0",
        environment="local",
        sink=sink,
        buffer_max=2,
    )
    for _ in range(5):
        logger.emit(
            event_type="business_event",
            event_version="1.0.0",
            severity="INFO",
            fields={"business_domain": "d", "action": "a"},
        )
    assert logger.buffer_size == 2
    assert logger.dropped_count == 3
