"""JSONL シンク: Hive パーティション形式でファイルに追記する。

パス規約 (設計書 §6.4.1):
  {root}/service_name={svc}/event_type={et}/dt={YYYY-MM-DD}/hour={HH}/{svc}_{et}_{dt}_{HH}.jsonl[.gz]

各 (event_type, dt, hour) シャード 1 ファイル。バッチごとに開閉。
DuckDB の `read_json_auto(..., hive_partitioning=true)` でそのままクエリできる。
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


class JsonlSink(Protocol):
    async def write_batch(self, lines: list[str]) -> None: ...


def _extract_event_type(line: str) -> str:
    try:
        obj = json.loads(line)
    except ValueError:
        return "unknown"
    if not isinstance(obj, dict):
        return "unknown"
    value = obj.get("event_type")
    return str(value) if value else "unknown"


def _extract_event_timestamp(line: str) -> datetime:
    try:
        obj = json.loads(line)
    except ValueError:
        return datetime.now(UTC)
    if not isinstance(obj, dict):
        return datetime.now(UTC)
    ts = obj.get("event_timestamp")
    if not ts:
        return datetime.now(UTC)
    try:
        # pydantic の datetime は ISO 8601 文字列。`Z` を `+00:00` に正規化。
        ts_str = str(ts).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(ts_str)
    except ValueError:
        return datetime.now(UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class RotatingFileSink:
    """Hive パーティションを (service_name, event_type, dt, hour) で掘るシンク。

    書込は event 自身の `event_timestamp` のパーティションに送る (遅延イベント対応)。
    `event_timestamp` が読めない場合は現在時刻 UTC にフォールバック。
    """

    def __init__(
        self,
        root_dir: Path | str,
        service_name: str,
        *,
        compress: bool = False,
    ) -> None:
        self._root = Path(root_dir)
        self._service = service_name
        self._compress = compress
        self._lock = asyncio.Lock()

    @property
    def service_name(self) -> str:
        return self._service

    def shard_path(self, event_type: str, ts: datetime) -> Path:
        ts_utc = ts.astimezone(UTC)
        dt_str = ts_utc.strftime("%Y-%m-%d")
        hour = ts_utc.strftime("%H")
        dir_path = (
            self._root
            / f"service_name={self._service}"
            / f"event_type={event_type}"
            / f"dt={dt_str}"
            / f"hour={hour}"
        )
        dir_path.mkdir(parents=True, exist_ok=True)
        suffix = ".jsonl.gz" if self._compress else ".jsonl"
        filename = f"{self._service}_{event_type}_{dt_str}_{hour}{suffix}"
        return dir_path / filename

    async def write_batch(self, lines: list[str]) -> None:
        if not lines:
            return
        grouped: dict[Path, list[str]] = {}
        for line in lines:
            et = _extract_event_type(line)
            ts = _extract_event_timestamp(line)
            path = self.shard_path(et, ts)
            grouped.setdefault(path, []).append(line)

        async with self._lock:
            for path, group in grouped.items():
                await asyncio.to_thread(self._append, path, group)

    def _append(self, path: Path, lines: list[str]) -> None:
        if self._compress:
            with gzip.open(path, "ab") as f:
                for line in lines:
                    f.write((line + "\n").encode("utf-8"))
        else:
            with open(path, "a", encoding="utf-8") as f:
                for line in lines:
                    f.write(line + "\n")
