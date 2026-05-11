"""PdfDocumentsRepo: `pdf_documents` テーブルへの薄い CRUD。

主な書き込み元:
- `yearly_navi_etl` (Phase 4-2e、申込ナビ PDF を chunk 化して入れる)
- 将来的に他 PDF (例: 概要 PDF) も同 schema で扱う想定

PK は `(pdf_id, chunk_index)`。Docling で章別 chunk 化する都合上、
**pdf_id 単位の全置換 (DELETE + INSERT) を 1 トランザクション** で行うのが正しい運用
(proposal 0003 §4.5.5)。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:  # pragma: no cover
    import asyncpg


class PdfDocumentRecord(BaseModel):
    """`pdf_documents` テーブル 1 行のモデル (1 chunk)。"""

    model_config = ConfigDict(frozen=True)

    pdf_id: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    url: str
    chunk_text: str = Field(min_length=1)
    embedding: list[float]
    page_number: int | None = None
    fetched_at: datetime
    pdf_hash: str
    schema_version: str = "v1"


class PdfDocumentsRepo:
    """`pdf_documents` テーブルへのアクセス Repository。"""

    def __init__(self, *, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def replace_for_pdf(self, *, pdf_id: str, records: list[PdfDocumentRecord]) -> int:
        """同一 pdf_id の chunk を全置換 (DELETE + INSERT を 1 トランザクション)。

        Returns:
            INSERT した件数 (空 list を渡した場合は 0、DELETE のみ実行)。
        """
        async with self._pool.acquire() as conn:
            await _register_vector(conn)
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM pdf_documents WHERE pdf_id = $1",
                    pdf_id,
                )
                for record in records:
                    await conn.execute(
                        """
                        INSERT INTO pdf_documents (
                            pdf_id, chunk_index, url, chunk_text, embedding,
                            page_number, fetched_at, pdf_hash, schema_version
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                        """,
                        record.pdf_id,
                        record.chunk_index,
                        record.url,
                        record.chunk_text,
                        record.embedding,
                        record.page_number,
                        record.fetched_at,
                        record.pdf_hash,
                        record.schema_version,
                    )
        return len(records)

    async def count(self, *, pdf_id: str | None = None) -> int:
        async with self._pool.acquire() as conn:
            if pdf_id is not None:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS c FROM pdf_documents WHERE pdf_id = $1",
                    pdf_id,
                )
            else:
                row = await conn.fetchrow("SELECT COUNT(*) AS c FROM pdf_documents")
        if row is None:
            return 0
        return int(row["c"])


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


async def _register_vector(conn: asyncpg.Connection) -> None:
    """`PgvectorStore._register_vector` と同パターン (lazy import)。"""
    try:
        from pgvector.asyncpg import register_vector
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "pgvector package is required (install with `uv sync --extra pgvector`)"
        ) from exc
    await register_vector(conn)


def _row_to_record(row: Any) -> PdfDocumentRecord:  # pragma: no cover — 将来の SELECT 用
    embedding = row["embedding"]
    if hasattr(embedding, "tolist"):
        embedding = embedding.tolist()
    return PdfDocumentRecord(
        pdf_id=row["pdf_id"],
        chunk_index=row["chunk_index"],
        url=row["url"],
        chunk_text=row["chunk_text"],
        embedding=list(embedding),
        page_number=row["page_number"],
        fetched_at=row["fetched_at"],
        pdf_hash=row["pdf_hash"],
        schema_version=row.get("schema_version", "v1"),
    )


__all__ = ["PdfDocumentRecord", "PdfDocumentsRepo"]
