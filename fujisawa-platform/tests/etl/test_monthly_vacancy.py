"""monthly_vacancy_etl のテスト。

空き状況 / 申込状況 の 2 PDF を fetch → archive.put → parse → upsert する Job 全体を
mock で検証する。Phase 4-2c-2 の PdfArchive を最初から DI に組み込み済み。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest
import respx

from fujisawa_platform.crawler import PoliteFetcher, PoliteFetcherConfig
from fujisawa_platform.etl._repos.vacancy import (
    ApplicationSnapshotRecord,
    VacancySnapshotRecord,
)
from fujisawa_platform.etl._runner import EtlRunResult
from fujisawa_platform.etl.monthly_vacancy import (
    MonthlyVacancyOutcome,
    crawl_and_upsert_vacancy,
    run_monthly_vacancy,
)
from fujisawa_platform.etl.pdf_archive import ArchivePut, LocalArchive
from fujisawa_platform.pdf_pipeline import PdfTable
from fujisawa_platform.resolver import FacilityResolver, ResolverEntry

_VACANCY_URL = "https://www.city.fujisawa.kanagawa.jp/.../akizyoukyou20260401a.pdf"
_APP_URL = "https://www.city.fujisawa.kanagawa.jp/.../mousikomizyoukyou20260401.pdf"


def _resolver() -> FacilityResolver:
    return FacilityResolver(
        [
            ResolverEntry(facility_id="kouritsu-aaa", canonical_name="藤沢保育園"),
            ResolverEntry(facility_id="kouritsu-bbb", canonical_name="辻堂保育園"),
        ]
    )


def _vacancy_pdf_table() -> PdfTable:
    return PdfTable(
        headers=["施設名", "0歳児", "1歳児", "2歳児"],
        rows=[
            ["藤沢保育園", "0", "1", "0"],
            ["辻堂保育園", "2", "0", "3"],
        ],
    )


def _application_pdf_table() -> PdfTable:
    return PdfTable(
        headers=["施設名", "0歳児定員", "0歳児申込", "1歳児定員", "1歳児申込"],
        rows=[
            ["藤沢保育園", "12", "30", "18", "20"],
            ["辻堂保育園", "9", "15", "12", "10"],
        ],
    )


class _RecordingVacancyRepo:
    def __init__(self) -> None:
        self.upserts: list[list[VacancySnapshotRecord]] = []

    async def upsert_many(self, records: list[VacancySnapshotRecord]) -> int:
        self.upserts.append(list(records))
        return len(records)


class _RecordingApplicationRepo:
    def __init__(self) -> None:
        self.upserts: list[list[ApplicationSnapshotRecord]] = []

    async def upsert_many(self, records: list[ApplicationSnapshotRecord]) -> int:
        self.upserts.append(list(records))
        return len(records)


class _RecordingArchive:
    def __init__(self) -> None:
        self.puts: list[dict[str, Any]] = []

    async def put(
        self,
        *,
        path: str,
        content: bytes,
        source_url: str,
        fetched_at: datetime,
    ) -> ArchivePut:
        self.puts.append(
            {
                "path": path,
                "content": content,
                "source_url": source_url,
                "fetched_at": fetched_at,
            }
        )
        return ArchivePut(backend="fake", path=path)

    async def get(self, path: str) -> bytes:
        return next(p["content"] for p in self.puts if p["path"] == path)

    async def exists(self, path: str) -> bool:
        return any(p["path"] == path for p in self.puts)


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


def _table_extractor(_: bytes) -> list[PdfTable]:
    """テスト用: PDF bytes を見ず空き状況 table 1 つを返す。"""
    return [_vacancy_pdf_table()]


# ─────────────────────────────────────────────────────────────────────
# crawl_and_upsert_vacancy
# ─────────────────────────────────────────────────────────────────────


class TestCrawlAndUpsertVacancy:
    @pytest.mark.asyncio
    @respx.mock
    async def test_upserts_both_vacancy_and_application(
        self, fetcher_config: PoliteFetcherConfig
    ) -> None:
        respx.get(_VACANCY_URL).mock(return_value=httpx.Response(200, content=b"%PDF-vac"))
        respx.get(_APP_URL).mock(return_value=httpx.Response(200, content=b"%PDF-app"))
        vacancy_repo = _RecordingVacancyRepo()
        application_repo = _RecordingApplicationRepo()

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_upsert_vacancy(
                vacancy_pdf_url=_VACANCY_URL,
                application_pdf_url=_APP_URL,
                year_month="2026-04",
                snapshot_date=date(2026, 4, 1),
                fetcher=fetcher,
                vacancy_repo=vacancy_repo,  # type: ignore[arg-type]
                application_repo=application_repo,  # type: ignore[arg-type]
                resolver=_resolver(),
                vacancy_extractor=lambda _: [_vacancy_pdf_table()],
                application_extractor=lambda _: [_application_pdf_table()],
                now=lambda: datetime(2026, 5, 11, 0, 0, tzinfo=UTC),
            )

        # vacancy: 2 施設 × 3 age_class = 6
        # application: 2 施設 × 2 age_class = 4
        assert outcome.vacancy_rows_written == 6
        assert outcome.application_rows_written == 4
        assert vacancy_repo.upserts[0]
        assert application_repo.upserts[0]

    @pytest.mark.asyncio
    @respx.mock
    async def test_archive_called_for_both_pdfs(self, fetcher_config: PoliteFetcherConfig) -> None:
        """空き / 申込 の両 PDF が archive.put される。"""
        respx.get(_VACANCY_URL).mock(return_value=httpx.Response(200, content=b"%PDF-vac"))
        respx.get(_APP_URL).mock(return_value=httpx.Response(200, content=b"%PDF-app"))
        archive = _RecordingArchive()

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_upsert_vacancy(
                vacancy_pdf_url=_VACANCY_URL,
                application_pdf_url=_APP_URL,
                year_month="2026-04",
                snapshot_date=date(2026, 4, 1),
                fetcher=fetcher,
                vacancy_repo=_RecordingVacancyRepo(),  # type: ignore[arg-type]
                application_repo=_RecordingApplicationRepo(),  # type: ignore[arg-type]
                resolver=_resolver(),
                archive=archive,  # type: ignore[arg-type]
                vacancy_extractor=_table_extractor,
                application_extractor=lambda _: [_application_pdf_table()],
            )

        assert len(archive.puts) == 2
        source_urls = {p["source_url"] for p in archive.puts}
        assert source_urls == {_VACANCY_URL, _APP_URL}
        # 両 PDF のパス情報が outcome に含まれる
        assert outcome.vacancy_archive_path is not None
        assert outcome.application_archive_path is not None
        assert outcome.vacancy_archive_path.startswith("monthly_vacancy_etl/2026/04/vacancy/")
        assert outcome.application_archive_path.startswith(
            "monthly_vacancy_etl/2026/04/application/"
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_dry_run_does_not_upsert_but_archives(
        self,
        tmp_path: Any,
        fetcher_config: PoliteFetcherConfig,
    ) -> None:
        respx.get(_VACANCY_URL).mock(return_value=httpx.Response(200, content=b"%PDF-vac"))
        respx.get(_APP_URL).mock(return_value=httpx.Response(200, content=b"%PDF-app"))
        archive = LocalArchive(root=tmp_path)
        vacancy_repo = _RecordingVacancyRepo()
        application_repo = _RecordingApplicationRepo()

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_upsert_vacancy(
                vacancy_pdf_url=_VACANCY_URL,
                application_pdf_url=_APP_URL,
                year_month="2026-04",
                snapshot_date=date(2026, 4, 1),
                fetcher=fetcher,
                vacancy_repo=vacancy_repo,  # type: ignore[arg-type]
                application_repo=application_repo,  # type: ignore[arg-type]
                resolver=_resolver(),
                archive=archive,
                vacancy_extractor=_table_extractor,
                application_extractor=lambda _: [_application_pdf_table()],
                dry_run=True,
            )

        assert vacancy_repo.upserts == []
        assert application_repo.upserts == []
        # archive には保存されている (出典担保)
        assert outcome.vacancy_archive_path is not None
        assert await archive.exists(outcome.vacancy_archive_path) is True
        assert outcome.application_archive_path is not None
        assert await archive.exists(outcome.application_archive_path) is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_vacancy_fetch_failure_propagates(
        self, fetcher_config: PoliteFetcherConfig
    ) -> None:
        respx.get(_VACANCY_URL).mock(return_value=httpx.Response(404))
        respx.get(_APP_URL).mock(return_value=httpx.Response(200, content=b"%PDF-app"))

        async with PoliteFetcher(fetcher_config) as fetcher:
            with pytest.raises(httpx.HTTPStatusError):
                await crawl_and_upsert_vacancy(
                    vacancy_pdf_url=_VACANCY_URL,
                    application_pdf_url=_APP_URL,
                    year_month="2026-04",
                    snapshot_date=date(2026, 4, 1),
                    fetcher=fetcher,
                    vacancy_repo=_RecordingVacancyRepo(),  # type: ignore[arg-type]
                    application_repo=_RecordingApplicationRepo(),  # type: ignore[arg-type]
                    resolver=_resolver(),
                    vacancy_extractor=_table_extractor,
                    application_extractor=lambda _: [_application_pdf_table()],
                )


# ─────────────────────────────────────────────────────────────────────
# run_monthly_vacancy (Cloud Run Job entrypoint)
# ─────────────────────────────────────────────────────────────────────


class TestRunMonthlyVacancy:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_success_result(self, fetcher_config: PoliteFetcherConfig) -> None:
        respx.get(_VACANCY_URL).mock(return_value=httpx.Response(200, content=b"%PDF-vac"))
        respx.get(_APP_URL).mock(return_value=httpx.Response(200, content=b"%PDF-app"))
        runs = _FakeRunsRepo()

        result = await run_monthly_vacancy(
            vacancy_pdf_url=_VACANCY_URL,
            application_pdf_url=_APP_URL,
            year_month="2026-04",
            snapshot_date=date(2026, 4, 1),
            fetcher_config=fetcher_config,
            vacancy_repo=_RecordingVacancyRepo(),  # type: ignore[arg-type]
            application_repo=_RecordingApplicationRepo(),  # type: ignore[arg-type]
            runs_repo=runs,  # type: ignore[arg-type]
            resolver=_resolver(),
            run_id="monthly_vacancy_etl-20260422-0300",
            vacancy_extractor=_table_extractor,
            application_extractor=lambda _: [_application_pdf_table()],
            now=lambda: datetime(2026, 5, 11, 0, 0, tzinfo=UTC),
        )

        assert isinstance(result, EtlRunResult)
        assert result.status == "success"
        # vacancy 6 + application 4 = 10
        assert result.rows_written == 10
        assert runs.finishes[0]["status"] == "success"

    @pytest.mark.asyncio
    @respx.mock
    async def test_application_fetch_failure_caught_by_runner(
        self, fetcher_config: PoliteFetcherConfig
    ) -> None:
        respx.get(_VACANCY_URL).mock(return_value=httpx.Response(200, content=b"%PDF-vac"))
        respx.get(_APP_URL).mock(return_value=httpx.Response(500))
        runs = _FakeRunsRepo()

        result = await run_monthly_vacancy(
            vacancy_pdf_url=_VACANCY_URL,
            application_pdf_url=_APP_URL,
            year_month="2026-04",
            snapshot_date=date(2026, 4, 1),
            fetcher_config=fetcher_config,
            vacancy_repo=_RecordingVacancyRepo(),  # type: ignore[arg-type]
            application_repo=_RecordingApplicationRepo(),  # type: ignore[arg-type]
            runs_repo=runs,  # type: ignore[arg-type]
            resolver=_resolver(),
            run_id="monthly_vacancy_etl-20260422-0300",
            vacancy_extractor=_table_extractor,
            application_extractor=lambda _: [_application_pdf_table()],
        )

        assert result.status == "failed"


class TestOutcomeModel:
    def test_frozen(self) -> None:
        outcome = MonthlyVacancyOutcome(
            vacancy_rows_written=6,
            application_rows_written=4,
            vacancy_tables_parsed=1,
            application_tables_parsed=1,
            vacancy_pdf_hash="a" * 64,
            application_pdf_hash="b" * 64,
        )
        with pytest.raises(Exception):
            outcome.vacancy_rows_written = 99  # type: ignore[misc]
