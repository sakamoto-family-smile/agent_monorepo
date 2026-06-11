"""`edinet_documents` テーブルへの async CRUD (proposal 0006 Phase 1e)。

PROPOSAL-0011 P3-B: 旧 raw aiosqlite 実装を SQLAlchemy 化し、shared Cloud SQL
(Postgres) に乗せる。dev/test は SQLite。`db_path` を渡すと専用 sqlite engine を
作る (テスト用)。未指定なら共有 engine (config.resolved_database_url) を使う。

設計:
- PK = `document_id` (immutable id from EDINET)
- 書類本体 (PDF / XBRL) のキャッシュ uri / 時刻も同テーブルで管理
- daily batch (rolling 7 日窓) で `upsert_many` 経由更新
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

from edinet_client import DocumentMetadata, DocumentType
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from services.db_engine import get_engine, get_sessionmaker
from services.db_models import EdinetDocument

logger = logging.getLogger(__name__)

# upsert 時に excluded で上書きする列 (status 系の遅延変更を反映)。
_UPSERT_COLS = (
    "edinet_code",
    "securities_code",
    "submitter_name",
    "document_type",
    "submit_date",
    "period_end",
    "description",
    "withdrawal_status",
    "disclosure_status",
    "doc_info_edit_status",
    "xbrl_flag",
    "pdf_flag",
    "attach_doc_flag",
)


@dataclass(frozen=True)
class EdinetDocumentRow:
    """`edinet_documents` テーブル 1 行を表す DTO。"""

    document_id: str
    edinet_code: str
    securities_code: str | None
    submitter_name: str
    document_type: str
    submit_date: date
    period_end: date | None
    description: str
    withdrawal_status: int
    disclosure_status: int
    doc_info_edit_status: int
    xbrl_flag: bool
    pdf_flag: bool
    attach_doc_flag: bool
    cache_uri: str | None
    cached_at: datetime | None

    @property
    def is_available(self) -> bool:
        return self.withdrawal_status == 0 and self.disclosure_status == 0

    def to_metadata(self) -> DocumentMetadata:
        """edinet_client の `DocumentMetadata` に戻す (orchestrator 等が利用)。"""
        try:
            doc_type: DocumentType | str = DocumentType(self.document_type)
        except ValueError:
            doc_type = self.document_type
        return DocumentMetadata(
            document_id=self.document_id,
            edinet_code=self.edinet_code,
            securities_code=self.securities_code,
            submitter_name=self.submitter_name,
            document_type=doc_type,
            submit_date=self.submit_date,
            period_end=self.period_end,
            description=self.description,
            withdrawal_status=self.withdrawal_status,
            disclosure_status=self.disclosure_status,
            doc_info_edit_status=self.doc_info_edit_status,
            xbrl_flag=self.xbrl_flag,
            pdf_flag=self.pdf_flag,
            attach_doc_flag=self.attach_doc_flag,
        )


class EdinetIndexRepo:
    """`edinet_documents` テーブルへの async CRUD (SQLAlchemy)。"""

    def __init__(self, db_path: str | None = None) -> None:
        if db_path:
            self._engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            self._sm = async_sessionmaker(self._engine, expire_on_commit=False)
        else:
            self._engine = get_engine()
            self._sm = get_sessionmaker()

    def _dialect_insert(self):
        if self._engine.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert  # noqa: PLC0415
        else:
            from sqlalchemy.dialects.sqlite import insert  # noqa: PLC0415
        return insert

    # 1 INSERT 文あたりの行数上限。asyncpg はパラメータ数 32,767 が上限
    # (16 列 × 2048 行 = 32,768 で超過)。有報ピーク日 (6 月上旬) は 1 日 2,000 件
    # を超えるため、余裕を持って分割する。
    _UPSERT_CHUNK_ROWS = 500

    async def upsert_many(self, items: Iterable[DocumentMetadata]) -> int:
        """`document_id` を PK として bulk upsert。戻り値は upsert 件数。

        既存行も毎回 UPDATE して status 系の遅延変更 (取下げ / 開示停止) を反映する
        (last_index_refreshed_at も更新)。cache 情報には触れない。

        実装上の注意 (P3-B 本番バックフィルで顕在化):
        - EDINET の日次 INDEX には同一 document_id が重複して現れることがある。
          Postgres の `ON CONFLICT DO UPDATE` は 1 文内で同じ行を 2 回更新できない
          (CardinalityViolation) ため、文に流す前に document_id で dedupe (後勝ち)。
        - asyncpg のパラメータ上限 (32,767) を超えないよう chunk 分割する。
        """
        now = datetime.now().isoformat(sep=" ", timespec="seconds")
        deduped: dict[str, dict] = {}
        for m in items:
            row = {**self._to_row_dict(m), "last_index_refreshed_at": now}
            deduped[row["document_id"]] = row  # 後勝ち
        rows = list(deduped.values())
        if not rows:
            return 0
        insert = self._dialect_insert()
        async with self._sm() as session:
            for i in range(0, len(rows), self._UPSERT_CHUNK_ROWS):
                chunk = rows[i : i + self._UPSERT_CHUNK_ROWS]
                stmt = insert(EdinetDocument).values(chunk)
                set_ = {c: getattr(stmt.excluded, c) for c in _UPSERT_COLS}
                set_["last_index_refreshed_at"] = now
                stmt = stmt.on_conflict_do_update(
                    index_elements=["document_id"], set_=set_
                )
                await session.execute(stmt)
            await session.commit()
        return len(rows)

    async def list_by_edinet_code(
        self,
        edinet_code: str,
        *,
        document_types: list[str] | None = None,
        limit: int | None = None,
    ) -> list[EdinetDocumentRow]:
        """指定 EDINET コードの提出日 降順の書類 (is_available のみ)。"""
        stmt = (
            select(EdinetDocument)
            .where(
                EdinetDocument.edinet_code == edinet_code,
                EdinetDocument.withdrawal_status == 0,
                EdinetDocument.disclosure_status == 0,
            )
            .order_by(EdinetDocument.submit_date.desc())
        )
        if document_types:
            stmt = stmt.where(EdinetDocument.document_type.in_(document_types))
        if limit is not None:
            stmt = stmt.limit(limit)
        async with self._sm() as session:
            rows = (await session.scalars(stmt)).all()
        return [self._row_to_dto(r) for r in rows]

    async def get_by_document_id(self, document_id: str) -> EdinetDocumentRow | None:
        async with self._sm() as session:
            row = await session.scalar(
                select(EdinetDocument).where(
                    EdinetDocument.document_id == document_id
                )
            )
        return self._row_to_dto(row) if row else None

    async def count(self) -> int:
        async with self._sm() as session:
            n = await session.scalar(
                select(func.count()).select_from(EdinetDocument)
            )
        return int(n or 0)

    async def set_cache_uri(self, document_id: str, cache_uri: str) -> None:
        now = datetime.now().isoformat(sep=" ", timespec="seconds")
        async with self._sm() as session:
            await session.execute(
                update(EdinetDocument)
                .where(EdinetDocument.document_id == document_id)
                .values(cache_uri=cache_uri, cached_at=now)
            )
            await session.commit()

    # ─── private ───────────────────────────────────────────────────

    @staticmethod
    def _to_row_dict(meta: DocumentMetadata) -> dict:
        doc_type_value = (
            meta.document_type.value
            if isinstance(meta.document_type, DocumentType)
            else str(meta.document_type)
        )
        return {
            "document_id": meta.document_id,
            "edinet_code": meta.edinet_code,
            "securities_code": meta.securities_code,
            "submitter_name": meta.submitter_name,
            "document_type": doc_type_value,
            "submit_date": meta.submit_date.isoformat(),
            "period_end": meta.period_end.isoformat() if meta.period_end else None,
            "description": meta.description,
            "withdrawal_status": meta.withdrawal_status,
            "disclosure_status": meta.disclosure_status,
            "doc_info_edit_status": meta.doc_info_edit_status,
            "xbrl_flag": 1 if meta.xbrl_flag else 0,
            "pdf_flag": 1 if meta.pdf_flag else 0,
            "attach_doc_flag": 1 if meta.attach_doc_flag else 0,
        }

    @staticmethod
    def _row_to_dto(row: EdinetDocument) -> EdinetDocumentRow:
        return EdinetDocumentRow(
            document_id=row.document_id,
            edinet_code=row.edinet_code,
            securities_code=row.securities_code,
            submitter_name=row.submitter_name,
            document_type=row.document_type,
            submit_date=date.fromisoformat(row.submit_date),
            period_end=date.fromisoformat(row.period_end) if row.period_end else None,
            description=row.description or "",
            withdrawal_status=int(row.withdrawal_status),
            disclosure_status=int(row.disclosure_status),
            doc_info_edit_status=int(row.doc_info_edit_status),
            xbrl_flag=bool(row.xbrl_flag),
            pdf_flag=bool(row.pdf_flag),
            attach_doc_flag=bool(row.attach_doc_flag),
            cache_uri=row.cache_uri,
            cached_at=(
                datetime.fromisoformat(row.cached_at) if row.cached_at else None
            ),
        )


__all__ = ["EdinetDocumentRow", "EdinetIndexRepo"]
