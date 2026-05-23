"""edinet_index_etl batch CLI のテスト。"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
from edinet_client import DocumentMetadata, DocumentType


_SCHEMA = """
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


async def _create_schema(p: Path) -> None:
    async with aiosqlite.connect(p) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


@pytest.fixture
async def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """各テストで独立した SQLite ファイルを使う + 必要 schema 作成。

    `init_db()` は import 時に DB_PATH を capture するため monkeypatch しても
    効かない。 schema を手動で作る。
    """
    p = tmp_path / "etl.db"
    await _create_schema(p)
    from config import settings

    monkeypatch.setattr(settings, "db_path", str(p), raising=False)
    monkeypatch.setattr(settings, "edinet_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "edinet_min_interval_sec", 0.001, raising=False)
    return p


class TestResolveTargetDates:
    def test_rolling_window_default(self) -> None:
        from batch.edinet_index_etl import _resolve_target_dates

        dates = _resolve_target_dates(rolling_days=3, from_date=None, to_date=None)
        today = date.today()
        # 昨日, 一昨日, 三昨日 (新→旧の順)
        assert dates == [
            today - timedelta(days=1),
            today - timedelta(days=2),
            today - timedelta(days=3),
        ]

    def test_explicit_range(self) -> None:
        from batch.edinet_index_etl import _resolve_target_dates

        dates = _resolve_target_dates(
            rolling_days=7,
            from_date=date(2026, 5, 1),
            to_date=date(2026, 5, 3),
        )
        assert dates == [date(2026, 5, 1), date(2026, 5, 2), date(2026, 5, 3)]

    def test_only_from_specified(self) -> None:
        from batch.edinet_index_etl import _resolve_target_dates

        today = date.today()
        dates = _resolve_target_dates(
            rolling_days=7, from_date=today, to_date=None
        )
        assert dates == [today]

    def test_invalid_range_raises(self) -> None:
        from batch.edinet_index_etl import _resolve_target_dates

        with pytest.raises(ValueError, match="must be"):
            _resolve_target_dates(
                rolling_days=7,
                from_date=date(2026, 5, 10),
                to_date=date(2026, 5, 1),
            )


class TestBatchRun:
    @pytest.mark.asyncio
    async def test_run_upserts_docs_from_fake_client(
        self, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from batch import edinet_index_etl
        from services.edinet_index_repo import EdinetIndexRepo

        # fake EdinetClient で 2 日分の INDEX を返す
        days = [date(2026, 5, 20), date(2026, 5, 21)]
        returned: dict[date, list[DocumentMetadata]] = {
            days[0]: [
                DocumentMetadata(
                    document_id="A1",
                    edinet_code="E12345",
                    submitter_name="キオクシア",
                    document_type=DocumentType.ANNUAL_REPORT,
                    submit_date=days[0],
                )
            ],
            days[1]: [
                DocumentMetadata(
                    document_id="Q1",
                    edinet_code="E12345",
                    submitter_name="キオクシア",
                    document_type=DocumentType.QUARTERLY_REPORT,
                    submit_date=days[1],
                ),
                DocumentMetadata(
                    document_id="A2",
                    edinet_code="E99999",
                    submitter_name="他社",
                    document_type=DocumentType.ANNUAL_REPORT,
                    submit_date=days[1],
                ),
            ],
        }

        class _FakeClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> "_FakeClient":
                return self

            async def __aexit__(self, *exc: Any) -> None:
                return None

            async def list_documents(self, target_date: date) -> list[DocumentMetadata]:
                return returned.get(target_date, [])

        monkeypatch.setattr(edinet_index_etl, "EdinetClient", _FakeClient)

        summary = await edinet_index_etl.run(days)
        assert summary["target_days"] == 2
        assert summary["succeeded_days"] == 2
        assert summary["failed_days"] == 0
        assert summary["upserted_documents"] == 3

        # DB 確認
        repo = EdinetIndexRepo()
        assert await repo.count() == 3
        rows = await repo.list_by_edinet_code("E12345")
        assert sorted(r.document_id for r in rows) == ["A1", "Q1"]

    @pytest.mark.asyncio
    async def test_run_continues_on_per_day_failure(
        self, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from batch import edinet_index_etl

        days = [date(2026, 5, 20), date(2026, 5, 21)]

        class _PartialFailClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> "_PartialFailClient":
                return self

            async def __aexit__(self, *exc: Any) -> None:
                return None

            async def list_documents(self, target_date: date) -> list[DocumentMetadata]:
                if target_date == days[0]:
                    raise RuntimeError("simulated 1-day failure")
                return [
                    DocumentMetadata(
                        document_id="Q1",
                        edinet_code="E12345",
                        submitter_name="キオクシア",
                        document_type=DocumentType.QUARTERLY_REPORT,
                        submit_date=target_date,
                    )
                ]

        monkeypatch.setattr(edinet_index_etl, "EdinetClient", _PartialFailClient)
        summary = await edinet_index_etl.run(days)
        assert summary["failed_days"] == 1
        assert summary["succeeded_days"] == 1
        assert summary["upserted_documents"] == 1

    @pytest.mark.asyncio
    async def test_run_without_api_key_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from batch import edinet_index_etl
        from config import settings as _s

        monkeypatch.setattr(_s, "edinet_api_key", "", raising=False)
        with pytest.raises(RuntimeError, match="EDINET_API_KEY"):
            await edinet_index_etl.run([date(2026, 5, 20)])
