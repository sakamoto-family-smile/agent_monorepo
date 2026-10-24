"""サブシステム間イベント (outbox 方式)。

発行側は自分の DB の ``events`` テーブルへ、状態変更と同じトランザクションで 1 行書く。
受信側は発行側 DB を読み取り専用で開き、処理済み位置を自分の ``event_cursors`` に記録する。
GCP に出すときは outbox → Pub/Sub の転送を足すだけで受信側は変わらない。

同じ内容を ``data/events/type=<type>/dt=YYYY-MM-DD/<producer>.jsonl`` に追記する。
こちらは運用 DB を作り直しても残る履歴アーカイブで、受信処理には使わない。
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, text

from .timeutil import utc_now_iso


@dataclass(frozen=True)
class Event:
    seq: int
    event_id: str
    type: str
    payload: dict[str, Any]
    occurred_at: str


def new_event_id() -> str:
    return f"evt_{uuid.uuid4().hex}"


class Outbox:
    """1 トランザクション内で発行したイベントを、commit 後に JSONL へミラーする。"""

    def __init__(self, events_dir: Path, producer: str) -> None:
        self._events_dir = events_dir
        self._producer = producer
        self._pending: list[dict[str, Any]] = []

    def publish(self, conn: Connection, type_: str, payload: dict[str, Any]) -> str:
        event_id = payload.get("event_id") or new_event_id()
        occurred_at = payload.get("occurred_at") or utc_now_iso()
        body = {**payload, "event_id": event_id, "occurred_at": occurred_at}
        conn.execute(
            text(
                "INSERT INTO events (event_id, type, payload, occurred_at) "
                "VALUES (:event_id, :type, :payload, :occurred_at)"
            ),
            {
                "event_id": event_id,
                "type": type_,
                "payload": json.dumps(body, ensure_ascii=False, sort_keys=True),
                "occurred_at": occurred_at,
            },
        )
        self._pending.append({"type": type_, **body})
        return event_id

    def flush(self) -> int:
        """commit 後に呼ぶ。JSONL へ追記した件数を返す。"""
        written = 0
        for record in self._pending:
            day = record["occurred_at"][:10]
            path = self._events_dir / f"type={record['type']}" / f"dt={day}" / f"{self._producer}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            written += 1
        self._pending = []
        return written

    def discard(self) -> None:
        """rollback 時に呼ぶ。"""
        self._pending = []


class Consumer:
    """発行側 DB (読み取り専用) からイベントを読み、自分の DB にカーソルを持つ。"""

    def __init__(self, source_engine: Engine, own_engine: Engine, source_name: str) -> None:
        self._source = source_engine
        self._own = own_engine
        self._name = source_name

    def last_seq(self) -> int:
        with self._own.connect() as conn:
            row = conn.execute(
                text("SELECT last_seq FROM event_cursors WHERE source = :s"), {"s": self._name}
            ).first()
        return int(row[0]) if row else 0

    def fetch(self, types: tuple[str, ...] | None = None, limit: int = 500) -> list[Event]:
        sql = "SELECT seq, event_id, type, payload, occurred_at FROM events WHERE seq > :seq"
        params: dict[str, Any] = {"seq": self.last_seq(), "limit": limit}
        if types:
            names = [f":t{i}" for i in range(len(types))]
            sql += f" AND type IN ({', '.join(names)})"
            params.update({f"t{i}": t for i, t in enumerate(types)})
        sql += " ORDER BY seq LIMIT :limit"
        with self._source.connect() as conn:
            rows = conn.execute(text(sql), params).all()
        return [Event(r[0], r[1], r[2], json.loads(r[3]), r[4]) for r in rows]

    def ack(self, seq: int, conn: Connection | None = None) -> None:
        """処理済み位置を進める。受信側の状態変更と同じトランザクションで呼ぶのが基本。"""
        stmt = text(
            "INSERT INTO event_cursors (source, last_seq, updated_at) VALUES (:s, :q, :u) "
            "ON CONFLICT(source) DO UPDATE SET last_seq = excluded.last_seq, "
            "updated_at = excluded.updated_at WHERE excluded.last_seq > event_cursors.last_seq"
        )
        params = {"s": self._name, "q": seq, "u": utc_now_iso()}
        if conn is not None:
            conn.execute(stmt, params)
            return
        with self._own.begin() as c:
            c.execute(stmt, params)
