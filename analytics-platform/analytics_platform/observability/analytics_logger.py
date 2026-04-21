"""AnalyticsLogger: 業務ログ JSONL を型安全に発行する本体。

フロー:
  1. `emit()` で呼び出し側が event_type + fields を渡す
  2. 共通フィールド (event_id=UUIDv7 / event_timestamp / trace_id 等) を自動付与
  3. Pydantic discriminated union でバリデーション (失敗時は即 raise)
  4. JSON 1行にシリアライズ → メモリリングバッファに append (O(1), nano オーダー)
  5. 背景タスク or 明示 `flush()` が呼ぶとシンクにバッチ書込

失敗時の戻し:
  - シンクが例外を吐いたらバッファに戻す → 次のフラッシュで再試行
  - バッファが満杯 (maxlen 到達) なら最古のイベントが押し出される (損失ログあり)
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import UTC, datetime

import uuid_utils.compat as uuid_utils

from .context import get_current_trace_context
from .schemas import Severity, validate_event
from .sinks.file_sink import JsonlSink

logger = logging.getLogger(__name__)


class AnalyticsLogger:
    def __init__(
        self,
        *,
        service_name: str,
        service_version: str,
        environment: str,
        sink: JsonlSink,
        buffer_max: int = 10_000,
    ) -> None:
        self._service_name = service_name
        self._service_version = service_version
        self._environment = environment
        self._sink = sink
        self._buffer: deque[str] = deque(maxlen=buffer_max)
        self._buffer_max = buffer_max
        self._dropped_count = 0

    # ----- properties for observability -----

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)

    @property
    def dropped_count(self) -> int:
        return self._dropped_count

    # ----- public API -----

    def emit(
        self,
        *,
        event_type: str,
        event_version: str,
        severity: Severity,
        fields: dict[str, object],
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> str:
        """1 イベントを検証してバッファに追加。戻り値は event_id。"""
        ctx = get_current_trace_context()
        payload: dict[str, object] = {
            "event_id": str(uuid_utils.uuid7()),
            "event_type": event_type,
            "event_version": event_version,
            "event_timestamp": datetime.now(UTC).isoformat(),
            "service_name": self._service_name,
            "service_version": self._service_version,
            "environment": self._environment,
            "trace_id": ctx["trace_id"],
            "span_id": ctx["span_id"],
            "user_id": user_id,
            "session_id": session_id,
            "severity": severity,
            **fields,
        }
        event = validate_event(payload)
        line = event.model_dump_json(exclude_none=False)

        if len(self._buffer) >= self._buffer_max:
            self._dropped_count += 1
            logger.error(
                "analytics_logger buffer full, oldest event dropped (dropped_count=%d)",
                self._dropped_count,
            )
        self._buffer.append(line)
        return json.loads(line)["event_id"]

    async def flush(self) -> int:
        """バッファを一括でシンクに書く。書けた件数を返す。失敗時は戻して raise。"""
        if not self._buffer:
            return 0
        batch: list[str] = []
        while self._buffer:
            batch.append(self._buffer.popleft())
        try:
            await self._sink.write_batch(batch)
            return len(batch)
        except Exception:
            # 失敗時は先頭に戻す (順序保持)
            self._buffer.extendleft(reversed(batch))
            logger.exception("flush_failed; returned %d events to buffer", len(batch))
            raise

    async def run(
        self,
        *,
        interval_seconds: float = 1.0,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """バックグラウンドフラッシュループ (オプション)。

        stop_event が set() されたら最終フラッシュしてから抜ける。
        """
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            try:
                await asyncio.wait_for(
                    stop_event.wait() if stop_event else asyncio.sleep(interval_seconds),
                    timeout=interval_seconds,
                )
            except TimeoutError:
                pass
            try:
                await self.flush()
            except Exception:
                # flush 内で既にログ済み。ループは継続。
                pass

        # 最終フラッシュ
        try:
            await self.flush()
        except Exception:
            pass
