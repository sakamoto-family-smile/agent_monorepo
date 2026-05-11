"""yearly_navi_etl: 申込ナビ PDF (47 ページ、14 MB) を pdf_documents に流す Job。

実行頻度 (proposal 0003 §4.5.4): 4 月・10 月 1 日 03:00 JST、Cloud Run Job として配備。

処理フロー:
  [1] 申込ナビ PDF を polite fetch
  [2] PdfArchive.put で原本保存 (proposal §4.5 line 204)
  [3] Docling `extract_chunks` で章別 chunk に分解
  [4] 各 chunk を embedding (Vertex or Mock)
  [5] PdfDocumentsRepo.replace_for_pdf で pdf_id 単位の全置換 (1 トランザクション)

書き込み先テーブル: `pdf_documents` (PK: pdf_id × chunk_index)
利用先: 保活 QAAgent + Score-Calc DSL (proposal 0005)。

なお、`rules/reiwa{N}/*.yaml` は本 Job ではなく **手動更新** 経路で扱う (proposal §4.5.4)。
本 Job は申込ナビ PDF を RAG で参照可能にすることのみが目的。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict

from fujisawa_platform.crawler import FetchResult, NotModified, PoliteFetcher, PoliteFetcherConfig
from fujisawa_platform.etl._repos.pdf_documents import PdfDocumentRecord
from fujisawa_platform.etl._runner import EtlRunResult, run_etl_job
from fujisawa_platform.etl.pdf_archive import NullArchive, PdfArchive, archive_path
from fujisawa_platform.knowledge_base import EmbeddingClient
from fujisawa_platform.pdf_pipeline import PdfChunk, extract_chunks

if TYPE_CHECKING:  # pragma: no cover
    from fujisawa_platform.etl._repos.etl_runs import EtlRunsRepo


class _DocsRepoLike(Protocol):
    async def replace_for_pdf(self, *, pdf_id: str, records: list[PdfDocumentRecord]) -> int: ...


# chunk 抽出関数の型 (テスト時に Docling を回避するため DI 可能)
ChunkExtractor = Callable[[bytes], list[PdfChunk]]


class NaviCrawlOutcome(BaseModel):
    """`crawl_and_index_navi` の戻り値。"""

    model_config = ConfigDict(frozen=True)

    chunks_written: int = 0
    pdf_hash: str | None = None
    archive_path: str | None = None
    archive_backend: str | None = None


async def crawl_and_index_navi(
    *,
    pdf_url: str,
    year: int,
    fetcher: PoliteFetcher,
    repo: _DocsRepoLike,
    embedder: EmbeddingClient,
    archive: PdfArchive | None = None,
    chunk_extractor: ChunkExtractor | None = None,
    now: Callable[[], datetime] | None = None,
    dry_run: bool = False,
) -> NaviCrawlOutcome:
    """申込ナビ PDF を fetch して `pdf_documents` を全置換する。

    Args:
        pdf_url: 申込ナビ PDF の URL。
        year: 対象年度 (西暦)。pdf_id ハッシュ計算とアーカイブパスに使う。
        fetcher: PoliteFetcher (consumer 側で `async with` 済)。
        repo: `PdfDocumentsRepo` (DI 可能)。
        embedder: 各 chunk を 768 dim ベクトルに変換。
        archive: PDF アーカイブ先 (default は `NullArchive`)。
        chunk_extractor: chunk 抽出関数 (default: `pdf_pipeline.extract_chunks`)。
            テストでは mock を注入可能。
        now: 任意。fetched_at の差し替え (テスト用)。
        dry_run: True なら parse / archive は行うが `repo.replace_for_pdf` を呼ばない。
    """
    _now = now or _utcnow
    _archive: PdfArchive = archive or NullArchive()
    _extract = chunk_extractor or extract_chunks
    fetched_at = _now()

    pdf_bytes, pdf_hash = await _fetch_pdf(fetcher, pdf_url)

    # [2] アーカイブ (parse 失敗でも原本だけは残す)
    destination = archive_path(
        job_name="yearly_navi_etl",
        url=pdf_url,
        year=year,
    )
    archive_result = await _archive.put(
        path=destination,
        content=pdf_bytes,
        source_url=pdf_url,
        fetched_at=fetched_at,
    )

    # [3] Docling chunk 抽出
    raw_chunks = _extract(pdf_bytes)

    # [4] 各 chunk を embedding + Record 化
    pdf_id = _sha256(pdf_url.encode("utf-8"))
    records: list[PdfDocumentRecord] = []
    for chunk in raw_chunks:
        embedding = embedder.embed(chunk.text)
        records.append(
            PdfDocumentRecord(
                pdf_id=pdf_id,
                chunk_index=chunk.chunk_index,
                url=pdf_url,
                chunk_text=chunk.text,
                embedding=embedding,
                page_number=chunk.page_number,
                fetched_at=fetched_at,
                pdf_hash=pdf_hash or "",
            )
        )

    # [5] 全置換 (空でも DELETE で古い chunk を消す)
    if not dry_run:
        await repo.replace_for_pdf(pdf_id=pdf_id, records=records)

    return NaviCrawlOutcome(
        chunks_written=len(records),
        pdf_hash=pdf_hash,
        archive_path=archive_result.path,
        archive_backend=archive_result.backend,
    )


async def run_yearly_navi(
    *,
    pdf_url: str,
    year: int,
    fetcher_config: PoliteFetcherConfig,
    docs_repo: _DocsRepoLike,
    runs_repo: EtlRunsRepo,
    embedder: EmbeddingClient,
    run_id: str,
    archive: PdfArchive | None = None,
    chunk_extractor: ChunkExtractor | None = None,
    now: Callable[[], datetime] | None = None,
    dry_run: bool = False,
) -> EtlRunResult:
    """Cloud Run Job のエントリポイント (run_etl_job ラップ)。"""

    async def _job() -> EtlRunResult:
        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_index_navi(
                pdf_url=pdf_url,
                year=year,
                fetcher=fetcher,
                repo=docs_repo,
                embedder=embedder,
                archive=archive,
                chunk_extractor=chunk_extractor,
                now=now,
                dry_run=dry_run,
            )
        return EtlRunResult(
            rows_written=outcome.chunks_written,
            source_url=pdf_url,
            source_hash=outcome.pdf_hash,
            status="success",
        )

    return await run_etl_job(
        job_name="yearly_navi_etl",
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


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "ChunkExtractor",
    "NaviCrawlOutcome",
    "crawl_and_index_navi",
    "run_yearly_navi",
]
