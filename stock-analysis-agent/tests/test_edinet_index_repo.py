"""EdinetIndexRepo のテスト。 sqlite ファイルは tmp_path 上で完結。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import aiosqlite
import pytest
from edinet_client import DocumentMetadata, DocumentType


@pytest.fixture
async def db_path(tmp_path: Path) -> Path:
    p = tmp_path / "test.db"
    # 必要 schema だけ用意 (database.py の init_db を呼ぶと seeding も走るので軽量化)
    async with aiosqlite.connect(p) as db:
        await db.executescript(
            """
            CREATE TABLE edinet_documents (
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
            """
        )
        await db.commit()
    return p


def _meta(
    *,
    doc_id: str,
    edinet_code: str,
    doc_type: DocumentType,
    submit: date,
    period: date | None = None,
    withdrawn: int = 0,
) -> DocumentMetadata:
    return DocumentMetadata(
        document_id=doc_id,
        edinet_code=edinet_code,
        securities_code="285A0",
        submitter_name="キオクシア",
        document_type=doc_type,
        submit_date=submit,
        period_end=period,
        description=f"{doc_type.name} {submit}",
        withdrawal_status=withdrawn,
        pdf_flag=True,
        xbrl_flag=True,
    )


class TestUpsertMany:
    @pytest.mark.asyncio
    async def test_insert_new_documents(self, db_path: Path) -> None:
        from services.edinet_index_repo import EdinetIndexRepo

        repo = EdinetIndexRepo(db_path=str(db_path))
        items = [
            _meta(
                doc_id="A1",
                edinet_code="E12345",
                doc_type=DocumentType.ANNUAL_REPORT,
                submit=date(2026, 5, 10),
            ),
            _meta(
                doc_id="Q1",
                edinet_code="E12345",
                doc_type=DocumentType.QUARTERLY_REPORT,
                submit=date(2026, 2, 14),
            ),
        ]
        n = await repo.upsert_many(items)
        assert n == 2
        assert await repo.count() == 2

    @pytest.mark.asyncio
    async def test_upsert_updates_existing(self, db_path: Path) -> None:
        """同じ document_id を 2 回 upsert したら 1 行のまま、 status が更新される。"""
        from services.edinet_index_repo import EdinetIndexRepo

        repo = EdinetIndexRepo(db_path=str(db_path))

        # 初回: withdrawal_status=0
        await repo.upsert_many(
            [
                _meta(
                    doc_id="A1",
                    edinet_code="E12345",
                    doc_type=DocumentType.ANNUAL_REPORT,
                    submit=date(2026, 5, 10),
                    withdrawn=0,
                )
            ]
        )
        # 2 回目: withdrawal_status=1 (取下げ反映)
        await repo.upsert_many(
            [
                _meta(
                    doc_id="A1",
                    edinet_code="E12345",
                    doc_type=DocumentType.ANNUAL_REPORT,
                    submit=date(2026, 5, 10),
                    withdrawn=1,
                )
            ]
        )
        assert await repo.count() == 1
        row = await repo.get_by_document_id("A1")
        assert row is not None
        assert row.withdrawal_status == 1
        assert row.is_available is False

    @pytest.mark.asyncio
    async def test_empty_input_returns_zero(self, db_path: Path) -> None:
        from services.edinet_index_repo import EdinetIndexRepo

        repo = EdinetIndexRepo(db_path=str(db_path))
        assert await repo.upsert_many([]) == 0

    @pytest.mark.asyncio
    async def test_duplicate_ids_in_one_batch_are_deduped(self, db_path: Path) -> None:
        """同一 batch 内の重複 document_id は後勝ちで 1 行に dedupe される。

        EDINET 日次 INDEX には同一 doc_id が重複して現れることがあり、Postgres の
        ON CONFLICT は 1 文内の同一行 2 回更新を拒否する (CardinalityViolation)。
        P3-B 本番バックフィル (2025-06-10) で顕在化した regression。
        """
        from services.edinet_index_repo import EdinetIndexRepo

        repo = EdinetIndexRepo(db_path=str(db_path))
        n = await repo.upsert_many(
            [
                _meta(
                    doc_id="DUP1",
                    edinet_code="E12345",
                    doc_type=DocumentType.ANNUAL_REPORT,
                    submit=date(2026, 5, 10),
                    withdrawn=0,
                ),
                _meta(
                    doc_id="DUP1",
                    edinet_code="E12345",
                    doc_type=DocumentType.ANNUAL_REPORT,
                    submit=date(2026, 5, 10),
                    withdrawn=1,  # 後勝ちでこちらが反映される
                ),
            ]
        )
        assert n == 1
        assert await repo.count() == 1
        row = await repo.get_by_document_id("DUP1")
        assert row is not None and row.withdrawal_status == 1

    @pytest.mark.asyncio
    async def test_large_batch_is_chunked(self, db_path: Path) -> None:
        """_UPSERT_CHUNK_ROWS 超の batch も分割して全行 upsert される。"""
        from services.edinet_index_repo import EdinetIndexRepo

        repo = EdinetIndexRepo(db_path=str(db_path))
        total = EdinetIndexRepo._UPSERT_CHUNK_ROWS + 50
        items = [
            _meta(
                doc_id=f"BIG{i:05d}",
                edinet_code="E12345",
                doc_type=DocumentType.ANNUAL_REPORT,
                submit=date(2026, 5, 10),
            )
            for i in range(total)
        ]
        assert await repo.upsert_many(items) == total
        assert await repo.count() == total


class TestListByEdinetCode:
    @pytest.mark.asyncio
    async def test_filters_by_code_and_type(self, db_path: Path) -> None:
        from services.edinet_index_repo import EdinetIndexRepo

        repo = EdinetIndexRepo(db_path=str(db_path))
        items = [
            _meta(
                doc_id="A1",
                edinet_code="E12345",
                doc_type=DocumentType.ANNUAL_REPORT,
                submit=date(2026, 5, 10),
            ),
            _meta(
                doc_id="Q1",
                edinet_code="E12345",
                doc_type=DocumentType.QUARTERLY_REPORT,
                submit=date(2026, 2, 14),
            ),
            _meta(
                doc_id="Q2",
                edinet_code="E12345",
                doc_type=DocumentType.QUARTERLY_REPORT,
                submit=date(2025, 11, 14),
            ),
            _meta(
                doc_id="OTHER",
                edinet_code="E99999",
                doc_type=DocumentType.ANNUAL_REPORT,
                submit=date(2026, 5, 1),
            ),
        ]
        await repo.upsert_many(items)

        # 四半期だけ取得
        quarterlies = await repo.list_by_edinet_code(
            "E12345",
            document_types=[DocumentType.QUARTERLY_REPORT.value],
        )
        assert [r.document_id for r in quarterlies] == ["Q1", "Q2"]  # submit_date DESC

    @pytest.mark.asyncio
    async def test_excludes_withdrawn_documents(self, db_path: Path) -> None:
        from services.edinet_index_repo import EdinetIndexRepo

        repo = EdinetIndexRepo(db_path=str(db_path))
        await repo.upsert_many(
            [
                _meta(
                    doc_id="A1",
                    edinet_code="E12345",
                    doc_type=DocumentType.ANNUAL_REPORT,
                    submit=date(2026, 5, 10),
                    withdrawn=0,
                ),
                _meta(
                    doc_id="A2",
                    edinet_code="E12345",
                    doc_type=DocumentType.ANNUAL_REPORT,
                    submit=date(2026, 4, 10),
                    withdrawn=1,
                ),
            ]
        )
        rows = await repo.list_by_edinet_code("E12345")
        # 取下げられた A2 は除外
        assert [r.document_id for r in rows] == ["A1"]

    @pytest.mark.asyncio
    async def test_limit(self, db_path: Path) -> None:
        from services.edinet_index_repo import EdinetIndexRepo

        repo = EdinetIndexRepo(db_path=str(db_path))
        await repo.upsert_many(
            [
                _meta(
                    doc_id=f"Q{i}",
                    edinet_code="E12345",
                    doc_type=DocumentType.QUARTERLY_REPORT,
                    submit=date(2026, m, 14),
                )
                for i, m in enumerate([2, 11, 8], start=1)
            ]
        )
        rows = await repo.list_by_edinet_code("E12345", limit=2)
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_to_metadata_roundtrip(self, db_path: Path) -> None:
        from services.edinet_index_repo import EdinetIndexRepo

        repo = EdinetIndexRepo(db_path=str(db_path))
        await repo.upsert_many(
            [
                _meta(
                    doc_id="A1",
                    edinet_code="E12345",
                    doc_type=DocumentType.ANNUAL_REPORT,
                    submit=date(2026, 5, 10),
                    period=date(2026, 3, 31),
                )
            ]
        )
        row = await repo.get_by_document_id("A1")
        assert row is not None
        meta = row.to_metadata()
        assert meta.document_id == "A1"
        assert meta.document_type == DocumentType.ANNUAL_REPORT
        assert meta.submit_date == date(2026, 5, 10)
        assert meta.period_end == date(2026, 3, 31)
        assert meta.pdf_flag is True


class TestSetCacheUri:
    @pytest.mark.asyncio
    async def test_updates_cache_fields(self, db_path: Path) -> None:
        from services.edinet_index_repo import EdinetIndexRepo

        repo = EdinetIndexRepo(db_path=str(db_path))
        await repo.upsert_many(
            [
                _meta(
                    doc_id="A1",
                    edinet_code="E12345",
                    doc_type=DocumentType.ANNUAL_REPORT,
                    submit=date(2026, 5, 10),
                )
            ]
        )
        await repo.set_cache_uri("A1", "gs://my-cache/edinet/pdf/A1.pdf")
        row = await repo.get_by_document_id("A1")
        assert row is not None
        assert row.cache_uri == "gs://my-cache/edinet/pdf/A1.pdf"
        assert row.cached_at is not None
