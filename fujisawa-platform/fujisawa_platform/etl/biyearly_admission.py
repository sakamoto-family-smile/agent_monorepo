"""biyearly_admission_etl: 4 月入所結果 PDF (1 次・2 次) を `admission_results` に流す Job。

実行頻度 (proposal 0003 §4.5.4): 2 月・3 月の指定日 03:00 JST、Cloud Run Job として配備。

処理フロー:
  [1] 4 月入所結果 PDF を polite fetch
  [2] Docling で表抽出 (`pdf_pipeline.extract_tables`)
  [3] `admission_parser.parse_admission_table` で AdmissionResultRecord 化
       - facility_id は `FacilityResolver` 経由で解決 (中黒等の表記ゆれ吸収)
  [4] AdmissionRepo.upsert_many で `admission_results` テーブルに UPSERT

書き込み先テーブル: `admission_results` (PK: facility_id × year × round × age_class)
利用先: 保活 StrategyAgent (proposal 0005)。

整合性 (proposal 0003 §4.5.5):
- PK が (year, round) で分離されているので partial insert 中も既存月の整合性は保たれる
- 同一 PDF を再 run しても UPSERT で冪等
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict

from fujisawa_platform.crawler import FetchResult, NotModified, PoliteFetcher, PoliteFetcherConfig
from fujisawa_platform.etl._repos.admission import AdmissionResultRecord
from fujisawa_platform.etl._runner import EtlRunResult, run_etl_job
from fujisawa_platform.etl.admission_parser import parse_admission_table
from fujisawa_platform.etl.pdf_archive import NullArchive, PdfArchive, archive_path
from fujisawa_platform.pdf_pipeline import PdfTable, extract_tables
from fujisawa_platform.resolver import FacilityResolver

if TYPE_CHECKING:  # pragma: no cover
    from fujisawa_platform.etl._repos.etl_runs import EtlRunsRepo


class _AdmissionRepoLike(Protocol):
    async def upsert_many(self, records: list[AdmissionResultRecord]) -> int: ...


# 表抽出関数の型。テストでは Docling を呼ばない mock を注入できるよう DI 可能にする。
TableExtractor = Callable[[bytes], list[PdfTable]]


class AdmissionCrawlOutcome(BaseModel):
    """`crawl_and_upsert_admission` の戻り値。"""

    model_config = ConfigDict(frozen=True)

    rows_written: int = 0
    tables_parsed: int = 0
    pdf_hash: str | None = None
    archive_path: str | None = None
    archive_backend: str | None = None


async def crawl_and_upsert_admission(
    *,
    pdf_url: str,
    year: int,
    round: str,
    fetcher: PoliteFetcher,
    repo: _AdmissionRepoLike,
    resolver: FacilityResolver,
    archive: PdfArchive | None = None,
    table_extractor: TableExtractor | None = None,
    now: Callable[[], datetime] | None = None,
    dry_run: bool = False,
) -> AdmissionCrawlOutcome:
    """PDF を fetch して `admission_results` を UPSERT する。

    Args:
        pdf_url: 入所結果 PDF の URL。
        year / round: PDF が示す年度・1 次/2 次 (env / 引数経由)。
        fetcher: PoliteFetcher (consumer 側で `async with` 済)。
        repo: `AdmissionRepo` (DI 可能)。
        resolver: 施設名 → facility_id 解決用 (build_facility_resolver で構築)。
        archive: PDF アーカイブ先 (default は `NullArchive` = 保存しない)。
            本番は `GcsArchive(bucket_name="fujisawa-pdf-archive")`、smoke は `LocalArchive`。
        table_extractor: 表抽出関数 (default: `pdf_pipeline.extract_tables`)。
            テストでは mock を注入可能。
        now: 任意。as_of の差し替え (テスト用)。
        dry_run: True なら parse / archive 共に行うが repo.upsert_many は呼ばない。
    """
    _now = now or _utcnow
    _extract = table_extractor or extract_tables
    _archive: PdfArchive = archive or NullArchive()
    as_of = _now()

    pdf_bytes, pdf_hash = await _fetch_pdf(fetcher, pdf_url)

    # PDF オリジナルバイトをアーカイブに保存 (proposal §4.5 line 204)。
    # URL 切れ後の遡及検証 / 出典担保のため、parse 前に必ず保存する。
    archive_destination = archive_path(
        job_name="biyearly_admission_etl",
        url=pdf_url,
        year=year,
        round=round,
    )
    archive_result = await _archive.put(
        path=archive_destination,
        content=pdf_bytes,
        source_url=pdf_url,
        fetched_at=as_of,
    )

    tables = _extract(pdf_bytes)

    records: list[AdmissionResultRecord] = []
    for table in tables:
        records.extend(
            parse_admission_table(
                table=table,
                year=year,
                round=round,
                source_pdf_url=pdf_url,
                as_of=as_of,
                resolver=resolver,
            )
        )

    if not dry_run and records:
        await repo.upsert_many(records)

    return AdmissionCrawlOutcome(
        rows_written=len(records),
        tables_parsed=len(tables),
        pdf_hash=pdf_hash,
        archive_path=archive_result.path,
        archive_backend=archive_result.backend,
    )


async def run_biyearly_admission(
    *,
    pdf_url: str,
    year: int,
    round: str,
    fetcher_config: PoliteFetcherConfig,
    admission_repo: _AdmissionRepoLike,
    runs_repo: EtlRunsRepo,
    resolver: FacilityResolver,
    run_id: str,
    archive: PdfArchive | None = None,
    table_extractor: TableExtractor | None = None,
    now: Callable[[], datetime] | None = None,
    dry_run: bool = False,
) -> EtlRunResult:
    """Cloud Run Job のエントリポイント (run_etl_job ラップ)。"""

    async def _job() -> EtlRunResult:
        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_upsert_admission(
                pdf_url=pdf_url,
                year=year,
                round=round,
                fetcher=fetcher,
                repo=admission_repo,
                resolver=resolver,
                archive=archive,
                table_extractor=table_extractor,
                now=now,
                dry_run=dry_run,
            )
        return EtlRunResult(
            rows_written=outcome.rows_written,
            source_url=pdf_url,
            source_hash=outcome.pdf_hash,
            status="success",
        )

    return await run_etl_job(
        job_name="biyearly_admission_etl",
        run_id=run_id,
        repo=runs_repo,
        fn=_job,
        now=now,
    )


async def _fetch_pdf(fetcher: PoliteFetcher, url: str) -> tuple[bytes, str | None]:
    """PDF を fetch して (bytes, sha256) を返す。

    PoliteFetcher は text 経由なので latin-1 でラウンドトリップして bytes 化する
    (httpx の text プロパティは bytes を内部 decode した文字列なので、PDF のように
    バイナリだと壊れる可能性がある。Phase 4-2c は parse 部分の単体テストが本丸で、
    実 PDF integration は Phase 4-2h デプロイ時に手動確認する想定)。
    """
    result = await fetcher.fetch(url)
    if isinstance(result, NotModified):
        return b"", None
    assert isinstance(result, FetchResult)
    # NOTE: PoliteFetcher は HTML 想定だが、PDF バイナリ取得時は text プロパティが
    # decode 済の str を返してしまう。Phase 4-2 段階では mock 経由でテストし、
    # 実機での PDF 取得 path 修正は Phase 4-2 後半の手動 smoke で対応する。
    raw = result.text.encode("latin-1", errors="ignore")
    return raw, _sha256(raw)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "AdmissionCrawlOutcome",
    "TableExtractor",
    "crawl_and_upsert_admission",
    "run_biyearly_admission",
]
