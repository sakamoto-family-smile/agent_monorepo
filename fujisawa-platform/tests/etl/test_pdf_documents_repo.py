"""PdfDocumentsRepo のテスト。

`pdf_documents` テーブルへの **pdf_id 単位の全置換** (DELETE + INSERT を 1 トランザクション)
を mock asyncpg.Pool で検証する。Docling で章別 chunk 化した結果を入れ直す前提のため、
chunk_index の更新ではなく全置換が正しい運用 (proposal 0003 §4.5.5)。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from fujisawa_platform.etl._repos.pdf_documents import (
    PdfDocumentRecord,
    PdfDocumentsRepo,
)
from tests.etl._stubs import StubConnection, StubPool

_NOW = datetime(2026, 5, 11, 0, 0, tzinfo=UTC)
_PDF_URL = "https://example.com/r8_navi.pdf"
_PDF_HASH = "a" * 64


def _chunk(
    *,
    pdf_id: str = "navi-2026",
    chunk_index: int = 0,
    chunk_text: str = "本文",
    embedding: list[float] | None = None,
    page_number: int | None = 19,
) -> PdfDocumentRecord:
    return PdfDocumentRecord(
        pdf_id=pdf_id,
        chunk_index=chunk_index,
        url=_PDF_URL,
        chunk_text=chunk_text,
        embedding=embedding if embedding is not None else [0.0] * 768,
        page_number=page_number,
        fetched_at=_NOW,
        pdf_hash=_PDF_HASH,
    )


class _TxConnection(StubConnection):
    """`async with conn.transaction():` をサポートする拡張。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.tx_entered = 0
        self.tx_exited = 0

    def transaction(self) -> _TxConnection:
        return self

    async def __aenter__(self) -> _TxConnection:
        self.tx_entered += 1
        return self

    async def __aexit__(self, *args: Any) -> None:
        self.tx_exited += 1


@pytest.fixture(autouse=True)
def _stub_register_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    """`pgvector.asyncpg.register_vector` を no-op に差し替える (test_pgvector_store と同じパターン)。"""
    from fujisawa_platform.etl._repos import pdf_documents

    async def _noop(_conn: Any) -> None:
        return None

    monkeypatch.setattr(pdf_documents, "_register_vector", _noop)


# ─────────────────────────────────────────────────────────────────────
# replace_for_pdf (全置換)
# ─────────────────────────────────────────────────────────────────────


class TestReplaceForPdf:
    @pytest.mark.asyncio
    async def test_deletes_then_inserts_in_single_transaction(self) -> None:
        conn = _TxConnection()
        repo = PdfDocumentsRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        await repo.replace_for_pdf(
            pdf_id="navi-2026",
            records=[_chunk(chunk_index=0), _chunk(chunk_index=1)],
        )

        assert conn.tx_entered == 1
        assert conn.tx_exited == 1

        # 1 つ目が DELETE WHERE pdf_id=$1、その後 INSERT 2 件
        assert len(conn.executed) == 3
        delete_sql, delete_args = conn.executed[0]
        assert "DELETE FROM pdf_documents" in delete_sql
        assert "WHERE pdf_id = $1" in delete_sql
        assert delete_args == ("navi-2026",)
        for sql, _ in conn.executed[1:]:
            assert "INSERT INTO pdf_documents" in sql

    @pytest.mark.asyncio
    async def test_inserts_all_columns(self) -> None:
        conn = _TxConnection()
        repo = PdfDocumentsRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        rec = _chunk(
            pdf_id="navi-2026",
            chunk_index=3,
            chunk_text="申込ナビ 第 3 章",
            embedding=[0.1, 0.2] + [0.0] * 766,
            page_number=20,
        )
        await repo.replace_for_pdf(pdf_id="navi-2026", records=[rec])

        _, insert_args = conn.executed[1]
        # 列順: pdf_id, chunk_index, url, chunk_text, embedding,
        #       page_number, fetched_at, pdf_hash, schema_version
        assert insert_args[0] == "navi-2026"
        assert insert_args[1] == 3
        assert insert_args[2] == _PDF_URL
        assert insert_args[3] == "申込ナビ 第 3 章"
        assert insert_args[4] == [0.1, 0.2] + [0.0] * 766
        assert insert_args[5] == 20
        assert insert_args[6] == _NOW
        assert insert_args[7] == _PDF_HASH
        assert insert_args[8] == "v1"

    @pytest.mark.asyncio
    async def test_empty_list_still_deletes(self) -> None:
        """0 件渡された場合でも DELETE は実行 (古い chunk を残さない)。"""
        conn = _TxConnection()
        repo = PdfDocumentsRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        await repo.replace_for_pdf(pdf_id="navi-2026", records=[])

        assert len(conn.executed) == 1
        sql, _ = conn.executed[0]
        assert "DELETE FROM pdf_documents" in sql


class TestCount:
    @pytest.mark.asyncio
    async def test_count_by_pdf_id(self) -> None:
        conn = StubConnection(fetchrow_results=[{"c": 47}])
        repo = PdfDocumentsRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        n = await repo.count(pdf_id="navi-2026")
        assert n == 47
        sql, args = conn.fetchrowed[0]
        assert "WHERE pdf_id = $1" in sql
        assert args == ("navi-2026",)

    @pytest.mark.asyncio
    async def test_count_returns_total_when_no_filter(self) -> None:
        conn = StubConnection(fetchrow_results=[{"c": 100}])
        repo = PdfDocumentsRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        n = await repo.count()
        assert n == 100


# ─────────────────────────────────────────────────────────────────────
# Record validation
# ─────────────────────────────────────────────────────────────────────


class TestPdfDocumentRecord:
    def test_chunk_index_non_negative(self) -> None:
        with pytest.raises(ValueError, match="chunk_index"):
            PdfDocumentRecord(
                pdf_id="x",
                chunk_index=-1,
                url=_PDF_URL,
                chunk_text="t",
                embedding=[0.0] * 768,
                fetched_at=_NOW,
                pdf_hash=_PDF_HASH,
            )

    def test_empty_chunk_text_rejected(self) -> None:
        with pytest.raises(ValueError, match="chunk_text"):
            PdfDocumentRecord(
                pdf_id="x",
                chunk_index=0,
                url=_PDF_URL,
                chunk_text="",
                embedding=[0.0] * 768,
                fetched_at=_NOW,
                pdf_hash=_PDF_HASH,
            )

    def test_frozen(self) -> None:
        rec = _chunk()
        with pytest.raises(Exception):
            rec.chunk_index = 99  # type: ignore[misc]
