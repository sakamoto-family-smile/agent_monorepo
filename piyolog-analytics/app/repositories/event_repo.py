"""SQLite イベントストア (aiosqlite) と冪等 UPSERT。

設計方針:
  - event_id は `sha1(family_id + ISO8601 timestamp + event_type + raw_text)` で決定論的に生成
  - INSERT OR IGNORE で重複挿入を無視 (冪等化)
  - raw_text_hash で原本単位の重複取込を弾く (同じファイルを 2 回送っても再取込しない)
  - ロールバックは Phase 1.5 で実装: batches テーブルに `rolled_back_at` 列を用意
    しておき、集計クエリは `rolled_back_at IS NULL` で絞る
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import astuple
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
from models.piyolog import ImportBatch, ParsedEvent, StoredEvent

JST = timezone(timedelta(hours=9), "Asia/Tokyo")

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def build_event_id(
    *,
    family_id: str,
    event_timestamp: str,
    event_type: str,
    raw_text: str,
) -> str:
    """決定論的な event_id を生成。

    同じ family が同じタイムスタンプで同じ raw の行を再送しても、
    同一 event_id になるので INSERT OR IGNORE で吸収できる。

    SHA1 を使うのは衝突耐性より決定論的 ID 生成の短さを優先したため。
    `usedforsecurity=False` で用途を明示し、bandit B324 を抑止する。
    """
    key = f"{family_id}|{event_timestamp}|{event_type}|{raw_text}"
    return hashlib.sha1(key.encode("utf-8"), usedforsecurity=False).hexdigest()


def compute_raw_text_hash(raw_text: str) -> str:
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


def parsed_to_stored(
    event: ParsedEvent,
    *,
    family_id: str,
    source_user_id: str,
    child_id: str,
    import_batch_id: str,
    imported_at: str,
) -> StoredEvent:
    ts_iso = event.timestamp.isoformat()
    date_str = event.timestamp.astimezone(JST).strftime("%Y-%m-%d")
    event_id = build_event_id(
        family_id=family_id,
        event_timestamp=ts_iso,
        event_type=event.event_type.value,
        raw_text=event.raw_text,
    )
    return StoredEvent(
        event_id=event_id,
        family_id=family_id,
        source_user_id=source_user_id,
        child_id=child_id,
        event_timestamp=ts_iso,
        event_date=date_str,
        event_type=event.event_type.value,
        volume_ml=event.volume_ml,
        left_minutes=event.left_minutes,
        right_minutes=event.right_minutes,
        sleep_minutes=event.sleep_minutes,
        temperature_c=event.temperature_c,
        weight_kg=event.weight_kg,
        height_cm=event.height_cm,
        head_circumference_cm=event.head_circumference_cm,
        memo=event.memo,
        raw_text=event.raw_text,
        import_batch_id=import_batch_id,
        imported_at=imported_at,
    )


class DuplicateImportError(Exception):
    """同じ原本ハッシュが既に取り込み済みの場合に投げる。"""

    def __init__(self, batch_id: str):
        super().__init__(f"raw text already imported as batch {batch_id}")
        self.batch_id = batch_id


class EventRepo:
    """SQLite 永続化 (aiosqlite)。

    プロセスで 1 インスタンス。`initialize()` でスキーマを流し込む。
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._initialized = False

    @asynccontextmanager
    async def _conn(self) -> AsyncIterator[aiosqlite.Connection]:
        # SQLite は WAL で並行読み書きしやすくする
        conn = await aiosqlite.connect(self._db_path)
        try:
            await conn.execute("PRAGMA journal_mode=WAL;")
            await conn.execute("PRAGMA foreign_keys=ON;")
            yield conn
        finally:
            await conn.close()

    async def initialize(self) -> None:
        if self._initialized:
            return
        # 親ディレクトリを作る (in-memory やテストで不要なら skip)
        if ":memory:" not in self._db_path:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        ddl = _SCHEMA_PATH.read_text(encoding="utf-8")
        async with self._conn() as conn:
            await conn.executescript(ddl)
            await conn.commit()
        self._initialized = True

    async def import_events(
        self,
        *,
        family_id: str,
        source_user_id: str,
        child_id: str,
        raw_text: str,
        source_filename: str | None,
        events: list[ParsedEvent],
    ) -> ImportBatch:
        """原本ハッシュで重複検査 → バッチ作成 → INSERT OR IGNORE で UPSERT。

        重複原本なら `DuplicateImportError` を raise。
        """
        raw_hash = compute_raw_text_hash(raw_text)
        now_iso = datetime.now(UTC).isoformat()
        batch_id = str(uuid.uuid4())

        async with self._conn() as conn:
            # 既存バッチ重複チェック (active かつ同 family 同 hash)
            async with conn.execute(
                "SELECT batch_id FROM import_batches "
                "WHERE family_id=? AND raw_text_hash=? AND rolled_back_at IS NULL",
                (family_id, raw_hash),
            ) as cur:
                row = await cur.fetchone()
                if row is not None:
                    raise DuplicateImportError(row[0])

            # バッチ挿入
            await conn.execute(
                "INSERT INTO import_batches "
                "(batch_id, family_id, source_user_id, source_filename, raw_text_hash, "
                " event_count, imported_at, rolled_back_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
                (
                    batch_id,
                    family_id,
                    source_user_id,
                    source_filename,
                    raw_hash,
                    len(events),
                    now_iso,
                ),
            )

            # イベント一括 INSERT (冪等)
            stored_rows = [
                astuple(
                    parsed_to_stored(
                        e,
                        family_id=family_id,
                        source_user_id=source_user_id,
                        child_id=child_id,
                        import_batch_id=batch_id,
                        imported_at=now_iso,
                    )
                )
                for e in events
            ]
            if stored_rows:
                await conn.executemany(
                    "INSERT OR IGNORE INTO piyolog_events ("
                    "  event_id, family_id, source_user_id, child_id,"
                    "  event_timestamp, event_date, event_type,"
                    "  volume_ml, left_minutes, right_minutes, sleep_minutes,"
                    "  temperature_c, weight_kg, height_cm, head_circumference_cm,"
                    "  memo, raw_text, import_batch_id, imported_at"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    stored_rows,
                )
            await conn.commit()

        return ImportBatch(
            batch_id=batch_id,
            family_id=family_id,
            source_user_id=source_user_id,
            source_filename=source_filename,
            raw_text_hash=raw_hash,
            event_count=len(events),
            imported_at=now_iso,
            rolled_back_at=None,
        )

    async def count_events(self, *, family_id: str) -> int:
        async with self._conn() as conn:
            async with conn.execute(
                "SELECT COUNT(*) FROM piyolog_events e "
                "INNER JOIN import_batches b ON e.import_batch_id = b.batch_id "
                "WHERE e.family_id = ? AND b.rolled_back_at IS NULL",
                (family_id,),
            ) as cur:
                row = await cur.fetchone()
                return int(row[0]) if row else 0

    async def fetch_events_in_range(
        self,
        *,
        family_id: str,
        date_from: str,
        date_to: str,
    ) -> list[tuple]:
        """指定期間のイベントを event_date 昇順で取得。

        戻り値は (event_timestamp, event_date, event_type, volume_ml, left_minutes,
        right_minutes, sleep_minutes, temperature_c, weight_kg, height_cm,
        head_circumference_cm, memo) のタプルのリスト。
        """
        async with self._conn() as conn:
            async with conn.execute(
                "SELECT e.event_timestamp, e.event_date, e.event_type,"
                "       e.volume_ml, e.left_minutes, e.right_minutes,"
                "       e.sleep_minutes, e.temperature_c, e.weight_kg,"
                "       e.height_cm, e.head_circumference_cm, e.memo "
                "FROM piyolog_events e "
                "INNER JOIN import_batches b ON e.import_batch_id = b.batch_id "
                "WHERE e.family_id = ? "
                "  AND e.event_date BETWEEN ? AND ? "
                "  AND b.rolled_back_at IS NULL "
                "ORDER BY e.event_timestamp ASC",
                (family_id, date_from, date_to),
            ) as cur:
                rows = await cur.fetchall()
                return [tuple(r) for r in rows]
