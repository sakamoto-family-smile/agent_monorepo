"""biyearly_admission_etl のテスト。

PDF fetch → table 抽出 → parse → upsert の流れを、Docling 部分を mock した状態で
検証する (proposal 0003 §4.5.4 / §4.6 Manual / E2E は実 PDF で別途実施)。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx

from fujisawa_platform.crawler import PoliteFetcher, PoliteFetcherConfig
from fujisawa_platform.etl._repos.admission import AdmissionResultRecord
from fujisawa_platform.etl._runner import EtlRunResult
from fujisawa_platform.etl.biyearly_admission import (
    AdmissionCrawlOutcome,
    crawl_and_upsert_admission,
    run_biyearly_admission,
)
from fujisawa_platform.pdf_pipeline import PdfTable
from fujisawa_platform.resolver import FacilityResolver, ResolverEntry

_PDF_URL = "https://www.city.fujisawa.kanagawa.jp/.../r8-admission-1st.pdf"


def _resolver() -> FacilityResolver:
    return FacilityResolver(
        [
            ResolverEntry(facility_id="kouritsu-aaa", canonical_name="藤沢保育園"),
            ResolverEntry(facility_id="kouritsu-bbb", canonical_name="辻堂保育園"),
        ]
    )


def _stub_pdf_table() -> PdfTable:
    return PdfTable(
        headers=[
            "施設名",
            "0歳児定員",
            "0歳児申込",
            "0歳児利用枠",
            "1歳児定員",
            "1歳児申込",
            "1歳児利用枠",
        ],
        rows=[
            ["藤沢保育園", "12", "30", "0", "18", "20", "1"],
            ["辻堂保育園", "9", "15", "0", "12", "10", "2"],
        ],
    )


class _RecordingAdmissionRepo:
    def __init__(self) -> None:
        self.upserts: list[list[AdmissionResultRecord]] = []

    async def upsert_many(self, records: list[AdmissionResultRecord]) -> int:
        self.upserts.append(list(records))
        return len(records)


class _FakeRunsRepo:
    def __init__(self) -> None:
        self.starts: list[dict[str, Any]] = []
        self.finishes: list[dict[str, Any]] = []

    async def start_run(self, **kwargs: Any) -> None:
        self.starts.append(kwargs)

    async def finish_run(self, **kwargs: Any) -> None:
        self.finishes.append(kwargs)

    async def recent_runs(self, job_name: str, *, limit: int = 5) -> list[Any]:
        return []


@pytest.fixture
def fetcher_config() -> PoliteFetcherConfig:
    return PoliteFetcherConfig(
        user_agent="fujisawa-etl-test/0.1 (https://example.com)",
        min_interval_sec=0.001,
        max_retries=1,
        backoff_base_sec=0.001,
    )


# ─────────────────────────────────────────────────────────────────────
# crawl_and_upsert_admission
# ─────────────────────────────────────────────────────────────────────


class TestCrawlAndUpsertAdmission:
    @pytest.mark.asyncio
    @respx.mock
    async def test_extracts_and_upserts(self, fetcher_config: PoliteFetcherConfig) -> None:
        respx.get(_PDF_URL).mock(return_value=httpx.Response(200, content=b"%PDF-fake"))
        repo = _RecordingAdmissionRepo()

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_upsert_admission(
                pdf_url=_PDF_URL,
                year=2026,
                round="1st",
                fetcher=fetcher,
                repo=repo,  # type: ignore[arg-type]
                resolver=_resolver(),
                # extract_tables を mock 注入 (実 Docling は呼ばない)
                table_extractor=lambda _: [_stub_pdf_table()],
                now=lambda: datetime(2026, 5, 11, 0, 0, tzinfo=UTC),
            )

        # 2 施設 × 2 age_class = 4 件
        assert outcome.rows_written == 4
        assert len(repo.upserts) == 1
        records = repo.upserts[0]
        assert len(records) == 4
        assert {(r.facility_id, r.age_class) for r in records} == {
            ("kouritsu-aaa", 0),
            ("kouritsu-aaa", 1),
            ("kouritsu-bbb", 0),
            ("kouritsu-bbb", 1),
        }
        assert all(r.year == 2026 and r.round == "1st" for r in records)

    @pytest.mark.asyncio
    @respx.mock
    async def test_dry_run_does_not_call_repo(self, fetcher_config: PoliteFetcherConfig) -> None:
        respx.get(_PDF_URL).mock(return_value=httpx.Response(200, content=b"%PDF-fake"))
        repo = _RecordingAdmissionRepo()

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_upsert_admission(
                pdf_url=_PDF_URL,
                year=2026,
                round="1st",
                fetcher=fetcher,
                repo=repo,  # type: ignore[arg-type]
                resolver=_resolver(),
                table_extractor=lambda _: [_stub_pdf_table()],
                dry_run=True,
            )

        assert outcome.rows_written == 4
        assert repo.upserts == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_zero_tables_returns_zero_rows(self, fetcher_config: PoliteFetcherConfig) -> None:
        respx.get(_PDF_URL).mock(return_value=httpx.Response(200, content=b"%PDF-fake"))
        repo = _RecordingAdmissionRepo()

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_upsert_admission(
                pdf_url=_PDF_URL,
                year=2026,
                round="1st",
                fetcher=fetcher,
                repo=repo,  # type: ignore[arg-type]
                resolver=_resolver(),
                table_extractor=lambda _: [],
            )

        assert outcome.rows_written == 0
        assert outcome.tables_parsed == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_pdf_fetch_failure_propagates(self, fetcher_config: PoliteFetcherConfig) -> None:
        respx.get(_PDF_URL).mock(return_value=httpx.Response(404))
        repo = _RecordingAdmissionRepo()

        async with PoliteFetcher(fetcher_config) as fetcher:
            with pytest.raises(httpx.HTTPStatusError):
                await crawl_and_upsert_admission(
                    pdf_url=_PDF_URL,
                    year=2026,
                    round="1st",
                    fetcher=fetcher,
                    repo=repo,  # type: ignore[arg-type]
                    resolver=_resolver(),
                    table_extractor=lambda _: [_stub_pdf_table()],
                )

        assert repo.upserts == []


# ─────────────────────────────────────────────────────────────────────
# run_biyearly_admission (Cloud Run Job entrypoint)
# ─────────────────────────────────────────────────────────────────────


class TestRunBiyearlyAdmission:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_success_result(self, fetcher_config: PoliteFetcherConfig) -> None:
        respx.get(_PDF_URL).mock(return_value=httpx.Response(200, content=b"%PDF-fake"))
        admission = _RecordingAdmissionRepo()
        runs = _FakeRunsRepo()

        result = await run_biyearly_admission(
            pdf_url=_PDF_URL,
            year=2026,
            round="1st",
            fetcher_config=fetcher_config,
            admission_repo=admission,  # type: ignore[arg-type]
            runs_repo=runs,  # type: ignore[arg-type]
            resolver=_resolver(),
            run_id="biyearly_admission_etl-20260511-0300",
            table_extractor=lambda _: [_stub_pdf_table()],
            now=lambda: datetime(2026, 5, 11, 0, 0, tzinfo=UTC),
        )

        assert isinstance(result, EtlRunResult)
        assert result.status == "success"
        assert result.rows_written == 4
        assert len(runs.finishes) == 1
        assert runs.finishes[0]["status"] == "success"

    @pytest.mark.asyncio
    @respx.mock
    async def test_pdf_failure_is_caught_by_runner(
        self, fetcher_config: PoliteFetcherConfig
    ) -> None:
        """個別 PDF fetch 失敗 → run_etl_job が `failed` で記録。"""
        respx.get(_PDF_URL).mock(return_value=httpx.Response(404))
        admission = _RecordingAdmissionRepo()
        runs = _FakeRunsRepo()

        result = await run_biyearly_admission(
            pdf_url=_PDF_URL,
            year=2026,
            round="1st",
            fetcher_config=fetcher_config,
            admission_repo=admission,  # type: ignore[arg-type]
            runs_repo=runs,  # type: ignore[arg-type]
            resolver=_resolver(),
            run_id="biyearly_admission_etl-20260511-0300",
            table_extractor=lambda _: [_stub_pdf_table()],
        )

        assert result.status == "failed"
        assert "404" in (result.error_message or "")
        assert admission.upserts == []


class TestAdmissionCrawlOutcomeModel:
    def test_frozen(self) -> None:
        outcome = AdmissionCrawlOutcome(
            rows_written=10,
            tables_parsed=1,
            pdf_hash="a" * 64,
        )
        with pytest.raises(Exception):
            outcome.rows_written = 99  # type: ignore[misc]
