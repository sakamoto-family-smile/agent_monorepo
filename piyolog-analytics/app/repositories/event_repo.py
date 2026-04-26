"""イベントストア (SQLAlchemy 2.0 async) と冪等 UPSERT。

設計方針:
  - `DATABASE_URL` で SQLite (dev/test) と Postgres (prod) を切替できる。両方で同一コードが動く。
  - `event_id = sha1(family_id + ISO8601 ts + event_type + raw_text)` で決定論的に生成。
  - INSERT 時は dialect-aware な `ON CONFLICT DO NOTHING` で重複を吸収 (冪等化)。
  - `raw_text_hash` で原本単位の重複を partial unique index でブロックし、
    かつアプリ側で先に SELECT して `DuplicateImportError` を返す。
  - ロールバックは Phase 1.5 で実装: batches テーブルの `rolled_back_at` 列で論理削除。
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta, timezone

from models.piyolog import ImportBatch, ParsedEvent, StoredEvent
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from .db import create_engine_for, make_sessionmaker, normalize_database_url
from .models import Base, ImportBatchRow, PiyologEvent

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9), "Asia/Tokyo")


def build_event_id(
    *,
    family_id: str,
    event_timestamp: str,
    event_type: str,
    raw_text: str,
) -> str:
    """決定論的な event_id を生成。

    同じ family が同じタイムスタンプで同じ raw の行を再送しても、
    同一 event_id になるので ON CONFLICT DO NOTHING で吸収できる。

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
    """SQLAlchemy 2.0 async ベースの永続化層。

    プロセスで 1 インスタンス。`initialize()` でスキーマを流し込む。
    `database_url` か `engine` のどちらか一方を渡す。
    後方互換: `db_path` (SQLite ファイルパス) も受け付ける。
    """

    def __init__(
        self,
        *,
        database_url: str | None = None,
        db_path: str | None = None,
        engine: AsyncEngine | None = None,
        echo: bool = False,
    ) -> None:
        if engine is not None:
            self._engine: AsyncEngine = engine
            self._owns_engine = False
        else:
            url = normalize_database_url(database_url, fallback_sqlite_path=db_path)
            self._engine = create_engine_for(url, echo=echo)
            self._owns_engine = True
        self._sessionmaker = make_sessionmaker(self._engine)
        self._initialized = False

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def dialect(self) -> str:
        return self._engine.dialect.name

    async def initialize(self) -> None:
        """`create_all` でスキーマを流し込む (idempotent)。

        本番 (Postgres) では Alembic migration を別途使う想定。
        この関数はテスト / SQLite dev で使う。
        """
        if self._initialized:
            return
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self._initialized = True

    async def dispose(self) -> None:
        """所有していたエンジンを片付ける (engine を外から渡された場合は no-op)。"""
        if self._owns_engine:
            await self._engine.dispose()

    # ----------------------------------------------------------------
    # Insert / dedup
    # ----------------------------------------------------------------

    def _on_conflict_do_nothing_stmt(self, model, rows: list[dict]):
        """dialect 別 INSERT ... ON CONFLICT DO NOTHING。"""
        if self.dialect == "postgresql":
            stmt = pg_insert(model).values(rows)
            return stmt.on_conflict_do_nothing(index_elements=[model.__table__.primary_key.columns.values()[0].name])
        if self.dialect == "sqlite":
            stmt = sqlite_insert(model).values(rows)
            return stmt.on_conflict_do_nothing(index_elements=[model.__table__.primary_key.columns.values()[0].name])
        raise RuntimeError(f"Unsupported dialect for upsert: {self.dialect}")

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
        """原本ハッシュで重複検査 → バッチ作成 → ON CONFLICT DO NOTHING で UPSERT。"""
        raw_hash = compute_raw_text_hash(raw_text)
        now_iso = datetime.now(UTC).isoformat()
        batch_id = str(uuid.uuid4())

        async with self._sessionmaker() as session:
            # 既存バッチ重複チェック
            stmt = select(ImportBatchRow.batch_id).where(
                ImportBatchRow.family_id == family_id,
                ImportBatchRow.raw_text_hash == raw_hash,
                ImportBatchRow.rolled_back_at.is_(None),
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing is not None:
                raise DuplicateImportError(existing)

            # バッチ挿入
            session.add(
                ImportBatchRow(
                    batch_id=batch_id,
                    family_id=family_id,
                    source_user_id=source_user_id,
                    source_filename=source_filename,
                    raw_text_hash=raw_hash,
                    event_count=len(events),
                    imported_at=now_iso,
                    rolled_back_at=None,
                )
            )

            # イベント一括 INSERT (冪等)
            if events:
                rows = [
                    asdict(
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
                stmt_insert = self._on_conflict_do_nothing_stmt(PiyologEvent, rows)
                await session.execute(stmt_insert)

            await session.commit()

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

    # ----------------------------------------------------------------
    # Queries
    # ----------------------------------------------------------------

    async def count_events(self, *, family_id: str) -> int:
        from sqlalchemy import func

        stmt = (
            select(func.count(PiyologEvent.event_id))
            .join(ImportBatchRow, PiyologEvent.import_batch_id == ImportBatchRow.batch_id)
            .where(
                PiyologEvent.family_id == family_id,
                ImportBatchRow.rolled_back_at.is_(None),
            )
        )
        async with self._sessionmaker() as session:
            result = await session.execute(stmt)
            return int(result.scalar_one() or 0)

    async def fetch_events_in_range(
        self,
        *,
        family_id: str,
        date_from: str,
        date_to: str,
    ) -> list[tuple]:
        """指定期間のイベントを `event_date` 昇順で取得。

        戻り値は (event_timestamp, event_date, event_type, volume_ml, left_minutes,
        right_minutes, sleep_minutes, temperature_c, weight_kg, height_cm,
        head_circumference_cm, memo) のタプルのリスト。
        既存呼出側との後方互換のためタプル列を維持。
        """
        cols = (
            PiyologEvent.event_timestamp,
            PiyologEvent.event_date,
            PiyologEvent.event_type,
            PiyologEvent.volume_ml,
            PiyologEvent.left_minutes,
            PiyologEvent.right_minutes,
            PiyologEvent.sleep_minutes,
            PiyologEvent.temperature_c,
            PiyologEvent.weight_kg,
            PiyologEvent.height_cm,
            PiyologEvent.head_circumference_cm,
            PiyologEvent.memo,
        )
        stmt = (
            select(*cols)
            .join(ImportBatchRow, PiyologEvent.import_batch_id == ImportBatchRow.batch_id)
            .where(
                PiyologEvent.family_id == family_id,
                PiyologEvent.event_date.between(date_from, date_to),
                ImportBatchRow.rolled_back_at.is_(None),
            )
            .order_by(PiyologEvent.event_timestamp.asc())
        )
        async with self._sessionmaker() as session:
            result = await session.execute(stmt)
            return [tuple(row) for row in result.all()]
