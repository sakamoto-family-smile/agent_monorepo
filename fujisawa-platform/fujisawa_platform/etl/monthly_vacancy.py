"""monthly_vacancy_etl: 月次の空き状況 + 申込状況 PDF を取り込む Job (proposal 0003 §4.5.4)。

実行頻度: 毎月 22 日 03:00 JST、Cloud Run Job として配備。

処理フロー (空き状況 / 申込状況 の 2 PDF を 1 Job 内で処理):
  [1] vacancy PDF を fetch → archive.put → 表抽出 → parse → vacancy_repo.upsert_many
  [2] application PDF を fetch → archive.put → 表抽出 → parse → application_repo.upsert_many

書き込み先テーブル: `vacancy_snapshots`, `application_snapshots`
利用先: 保活 VacancyAgent (proposal 0005)。

整合性 (proposal 0003 §4.5.5):
- PK が (facility_id, year_month, age_class) で year_month 分離されているので、
  partial insert 中も既存月の整合性は保たれる
- 同一 PDF を再 run しても UPSERT で冪等
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict

from fujisawa_platform.crawler import FetchResult, NotModified, PoliteFetcher, PoliteFetcherConfig
from fujisawa_platform.etl._repos.vacancy import (
    ApplicationSnapshotRecord,
    VacancySnapshotRecord,
)
from fujisawa_platform.etl._runner import EtlRunResult, run_etl_job
from fujisawa_platform.etl.pdf_archive import NullArchive, PdfArchive, archive_path
from fujisawa_platform.etl.vacancy_parser import (
    parse_application_table,
    parse_vacancy_table,
)
from fujisawa_platform.pdf_pipeline import PdfTable, extract_tables
from fujisawa_platform.resolver import FacilityResolver

if TYPE_CHECKING:  # pragma: no cover
    from fujisawa_platform.etl._repos.etl_runs import EtlRunsRepo


class _VacancyRepoLike(Protocol):
    async def upsert_many(self, records: list[VacancySnapshotRecord]) -> int: ...


class _ApplicationRepoLike(Protocol):
    async def upsert_many(self, records: list[ApplicationSnapshotRecord]) -> int: ...


TableExtractor = Callable[[bytes], list[PdfTable]]


class MonthlyVacancyOutcome(BaseModel):
    """`crawl_and_upsert_vacancy` の戻り値。"""

    model_config = ConfigDict(frozen=True)

    vacancy_rows_written: int = 0
    application_rows_written: int = 0
    vacancy_tables_parsed: int = 0
    application_tables_parsed: int = 0
    vacancy_pdf_hash: str | None = None
    application_pdf_hash: str | None = None
    vacancy_archive_path: str | None = None
    application_archive_path: str | None = None


async def crawl_and_upsert_vacancy(
    *,
    vacancy_pdf_url: str,
    application_pdf_url: str,
    year_month: str,
    snapshot_date: date,
    fetcher: PoliteFetcher,
    vacancy_repo: _VacancyRepoLike,
    application_repo: _ApplicationRepoLike,
    resolver: FacilityResolver,
    archive: PdfArchive | None = None,
    vacancy_extractor: TableExtractor | None = None,
    application_extractor: TableExtractor | None = None,
    now: Callable[[], datetime] | None = None,
    dry_run: bool = False,
) -> MonthlyVacancyOutcome:
    """空き状況 + 申込状況 PDF を取り込んで両 snapshot テーブルを UPSERT する。

    Args:
        vacancy_pdf_url: 空き状況 PDF の URL。
        application_pdf_url: 申込状況 PDF の URL。
        year_month: 'YYYY-MM' 形式 (両テーブルの PK 構成要素)。
        snapshot_date: PDF 掲載日 (両テーブルに記録)。
        fetcher: PoliteFetcher (`async with` 済)。
        vacancy_repo / application_repo: DI 可能。
        resolver: 施設名 → facility_id 解決 (build_facility_resolver で構築)。
        archive: PDF アーカイブ先 (default は NullArchive)。
        vacancy_extractor / application_extractor: 表抽出関数 (default: pdf_pipeline.extract_tables)。
            テストでは mock を注入。
        now: as_of 差し替え用 (テスト)。
        dry_run: True なら parse / archive は行うが repo.upsert_many を呼ばない。
    """
    _now = now or _utcnow
    _vac_extract = vacancy_extractor or extract_tables
    _app_extract = application_extractor or extract_tables
    _archive: PdfArchive = archive or NullArchive()
    fetched_at = _now()

    # [1] 空き状況
    vacancy_pdf, vacancy_hash = await _fetch_pdf(fetcher, vacancy_pdf_url)
    vacancy_path = archive_path(
        job_name="monthly_vacancy_etl",
        url=vacancy_pdf_url,
        year=int(year_month[:4]),
        round=f"{year_month[5:]}/vacancy",
    )
    vacancy_archive_result = await _archive.put(
        path=vacancy_path,
        content=vacancy_pdf,
        source_url=vacancy_pdf_url,
        fetched_at=fetched_at,
    )
    vacancy_tables = _vac_extract(vacancy_pdf)
    vacancy_records: list[VacancySnapshotRecord] = []
    for table in vacancy_tables:
        vacancy_records.extend(
            parse_vacancy_table(
                table=table,
                year_month=year_month,
                snapshot_date=snapshot_date,
                source_pdf_url=vacancy_pdf_url,
                fetched_at=fetched_at,
                resolver=resolver,
            )
        )

    # [2] 申込状況
    application_pdf, application_hash = await _fetch_pdf(fetcher, application_pdf_url)
    application_path = archive_path(
        job_name="monthly_vacancy_etl",
        url=application_pdf_url,
        year=int(year_month[:4]),
        round=f"{year_month[5:]}/application",
    )
    application_archive_result = await _archive.put(
        path=application_path,
        content=application_pdf,
        source_url=application_pdf_url,
        fetched_at=fetched_at,
    )
    application_tables = _app_extract(application_pdf)
    application_records: list[ApplicationSnapshotRecord] = []
    for table in application_tables:
        application_records.extend(
            parse_application_table(
                table=table,
                year_month=year_month,
                snapshot_date=snapshot_date,
                source_pdf_url=application_pdf_url,
                fetched_at=fetched_at,
                resolver=resolver,
            )
        )

    if not dry_run:
        if vacancy_records:
            await vacancy_repo.upsert_many(vacancy_records)
        if application_records:
            await application_repo.upsert_many(application_records)

    return MonthlyVacancyOutcome(
        vacancy_rows_written=len(vacancy_records),
        application_rows_written=len(application_records),
        vacancy_tables_parsed=len(vacancy_tables),
        application_tables_parsed=len(application_tables),
        vacancy_pdf_hash=vacancy_hash,
        application_pdf_hash=application_hash,
        vacancy_archive_path=vacancy_archive_result.path,
        application_archive_path=application_archive_result.path,
    )


async def run_monthly_vacancy(
    *,
    vacancy_pdf_url: str,
    application_pdf_url: str,
    year_month: str,
    snapshot_date: date,
    fetcher_config: PoliteFetcherConfig,
    vacancy_repo: _VacancyRepoLike,
    application_repo: _ApplicationRepoLike,
    runs_repo: EtlRunsRepo,
    resolver: FacilityResolver,
    run_id: str,
    archive: PdfArchive | None = None,
    vacancy_extractor: TableExtractor | None = None,
    application_extractor: TableExtractor | None = None,
    now: Callable[[], datetime] | None = None,
    dry_run: bool = False,
) -> EtlRunResult:
    """Cloud Run Job のエントリポイント。"""

    async def _job() -> EtlRunResult:
        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_upsert_vacancy(
                vacancy_pdf_url=vacancy_pdf_url,
                application_pdf_url=application_pdf_url,
                year_month=year_month,
                snapshot_date=snapshot_date,
                fetcher=fetcher,
                vacancy_repo=vacancy_repo,
                application_repo=application_repo,
                resolver=resolver,
                archive=archive,
                vacancy_extractor=vacancy_extractor,
                application_extractor=application_extractor,
                now=now,
                dry_run=dry_run,
            )
        return EtlRunResult(
            rows_written=outcome.vacancy_rows_written + outcome.application_rows_written,
            source_url=vacancy_pdf_url,
            source_hash=_combine_hashes(outcome.vacancy_pdf_hash, outcome.application_pdf_hash),
            status="success",
        )

    return await run_etl_job(
        job_name="monthly_vacancy_etl",
        run_id=run_id,
        repo=runs_repo,
        fn=_job,
        now=now,
    )


async def _fetch_pdf(fetcher: PoliteFetcher, url: str) -> tuple[bytes, str | None]:
    result = await fetcher.fetch(url)
    if isinstance(result, NotModified):
        return b"", None
    assert isinstance(result, FetchResult)
    raw = result.text.encode("latin-1", errors="ignore")
    return raw, _sha256(raw)


def _combine_hashes(vacancy_hash: str | None, application_hash: str | None) -> str | None:
    """2 PDF のハッシュを 1 つに合成 (どちらかでも変われば run する判定)。"""
    if vacancy_hash is None and application_hash is None:
        return None
    combined = f"{vacancy_hash or ''}/{application_hash or ''}"
    return _sha256(combined.encode("utf-8"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "MonthlyVacancyOutcome",
    "TableExtractor",
    "crawl_and_upsert_vacancy",
    "run_monthly_vacancy",
]
