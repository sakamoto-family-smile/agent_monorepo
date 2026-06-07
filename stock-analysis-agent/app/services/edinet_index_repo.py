"""`edinet_documents` テーブルへの async CRUD (proposal 0006 Phase 1e)。

stock-analysis-agent の SQLite (`stock_analysis.db`) に乗せる。 Cloud SQL に
移行する際は本 module の SQL 互換性を確認する想定。

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

import aiosqlite
from edinet_client import DocumentMetadata, DocumentType

from config import settings

logger = logging.getLogger(__name__)


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
    """`edinet_documents` テーブルへの async CRUD。"""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or settings.db_path

    # NOTE (PROPOSAL-0011 P2-B): core 4 テーブルは SQLAlchemy/Postgres へ移行したが、
    # EDINET (edinet_documents) は EDINET 有効化 (P3) まで aiosqlite のまま据え置く。
    # core の init_db が本テーブルを作らなくなったため、batch は ensure_schema() で
    # 自前に SQLite スキーマを用意する。P3 で shared Cloud SQL へ移行予定。
    async def ensure_schema(self) -> None:
        """edinet_documents テーブルを (無ければ) 作成する。SQLite 専用 (P3 で移行)。"""
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS edinet_documents (
                    document_id TEXT PRIMARY KEY,
                    edinet_code TEXT NOT NULL,
                    securities_code TEXT,
                    submitter_name TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    submit_date TEXT NOT NULL,
                    period_end TEXT,
                    description TEXT DEFAULT '',
                    withdrawal_status INTEGER NOT NULL DEFAULT 0,
                    disclosure_status INTEGER NOT NULL DEFAULT 0,
                    doc_info_edit_status INTEGER NOT NULL DEFAULT 0,
                    xbrl_flag INTEGER NOT NULL DEFAULT 0,
                    pdf_flag INTEGER NOT NULL DEFAULT 0,
                    attach_doc_flag INTEGER NOT NULL DEFAULT 0,
                    cache_uri TEXT,
                    cached_at TEXT,
                    first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
                    last_index_refreshed_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_edinet_docs_sec_code_date
                    ON edinet_documents (securities_code, submit_date DESC);
                CREATE INDEX IF NOT EXISTS idx_edinet_docs_edinet_code_date
                    ON edinet_documents (edinet_code, submit_date DESC);
                CREATE INDEX IF NOT EXISTS idx_edinet_docs_type_date
                    ON edinet_documents (document_type, submit_date DESC);
                """
            )
            await db.commit()

    async def upsert_many(self, items: Iterable[DocumentMetadata]) -> int:
        """`document_id` を PK として bulk upsert。 戻り値は upsert された件数。

        status 系フィールドの遅延変更を反映するため、 既存行も毎回 UPDATE する
        (last_index_refreshed_at も更新)。 cache 情報 (cache_uri / cached_at) は
        ここでは触らない (別途 `set_cache_uri` で更新)。
        """
        rows = [self._to_row_values(meta) for meta in items]
        if not rows:
            return 0
        async with aiosqlite.connect(self._db_path) as db:
            await db.executemany(
                """
                INSERT INTO edinet_documents (
                    document_id, edinet_code, securities_code, submitter_name,
                    document_type, submit_date, period_end, description,
                    withdrawal_status, disclosure_status, doc_info_edit_status,
                    xbrl_flag, pdf_flag, attach_doc_flag,
                    last_index_refreshed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(document_id) DO UPDATE SET
                    edinet_code            = excluded.edinet_code,
                    securities_code        = excluded.securities_code,
                    submitter_name         = excluded.submitter_name,
                    document_type          = excluded.document_type,
                    submit_date            = excluded.submit_date,
                    period_end             = excluded.period_end,
                    description            = excluded.description,
                    withdrawal_status      = excluded.withdrawal_status,
                    disclosure_status      = excluded.disclosure_status,
                    doc_info_edit_status   = excluded.doc_info_edit_status,
                    xbrl_flag              = excluded.xbrl_flag,
                    pdf_flag               = excluded.pdf_flag,
                    attach_doc_flag        = excluded.attach_doc_flag,
                    last_index_refreshed_at = datetime('now')
                """,
                rows,
            )
            await db.commit()
        return len(rows)

    async def list_by_edinet_code(
        self,
        edinet_code: str,
        *,
        document_types: list[str] | None = None,
        limit: int | None = None,
    ) -> list[EdinetDocumentRow]:
        """指定 EDINET コードの書類を提出日 降順で返す。

        is_available (withdrawal_status=0 AND disclosure_status=0) のみ。
        """
        conds = [
            "edinet_code = ?",
            "withdrawal_status = 0",
            "disclosure_status = 0",
        ]
        params: list[object] = [edinet_code]
        if document_types:
            placeholders = ",".join("?" for _ in document_types)
            conds.append(f"document_type IN ({placeholders})")
            params.extend(document_types)
        where = " AND ".join(conds)
        sql = (
            "SELECT * FROM edinet_documents "
            f"WHERE {where} ORDER BY submit_date DESC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, params) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_dto(r) for r in rows]

    async def get_by_document_id(self, document_id: str) -> EdinetDocumentRow | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM edinet_documents WHERE document_id = ?",
                (document_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return self._row_to_dto(row) if row else None

    async def count(self) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM edinet_documents") as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def set_cache_uri(self, document_id: str, cache_uri: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """UPDATE edinet_documents
                   SET cache_uri = ?, cached_at = datetime('now')
                   WHERE document_id = ?""",
                (cache_uri, document_id),
            )
            await db.commit()

    # ─── private ───────────────────────────────────────────────────

    @staticmethod
    def _to_row_values(meta: DocumentMetadata) -> tuple:
        doc_type_value = (
            meta.document_type.value
            if isinstance(meta.document_type, DocumentType)
            else str(meta.document_type)
        )
        return (
            meta.document_id,
            meta.edinet_code,
            meta.securities_code,
            meta.submitter_name,
            doc_type_value,
            meta.submit_date.isoformat(),
            meta.period_end.isoformat() if meta.period_end else None,
            meta.description,
            meta.withdrawal_status,
            meta.disclosure_status,
            meta.doc_info_edit_status,
            1 if meta.xbrl_flag else 0,
            1 if meta.pdf_flag else 0,
            1 if meta.attach_doc_flag else 0,
        )

    @staticmethod
    def _row_to_dto(row: aiosqlite.Row) -> EdinetDocumentRow:
        return EdinetDocumentRow(
            document_id=row["document_id"],
            edinet_code=row["edinet_code"],
            securities_code=row["securities_code"],
            submitter_name=row["submitter_name"],
            document_type=row["document_type"],
            submit_date=date.fromisoformat(row["submit_date"]),
            period_end=date.fromisoformat(row["period_end"]) if row["period_end"] else None,
            description=row["description"] or "",
            withdrawal_status=int(row["withdrawal_status"]),
            disclosure_status=int(row["disclosure_status"]),
            doc_info_edit_status=int(row["doc_info_edit_status"]),
            xbrl_flag=bool(row["xbrl_flag"]),
            pdf_flag=bool(row["pdf_flag"]),
            attach_doc_flag=bool(row["attach_doc_flag"]),
            cache_uri=row["cache_uri"],
            cached_at=(
                datetime.fromisoformat(row["cached_at"]) if row["cached_at"] else None
            ),
        )


__all__ = ["EdinetDocumentRow", "EdinetIndexRepo"]
