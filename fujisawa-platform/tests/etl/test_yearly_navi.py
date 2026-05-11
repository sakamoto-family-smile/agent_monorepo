"""yearly_navi_etl のテスト。

申込ナビ PDF (47 ページ、14 MB) を取得 → archive.put → extract_chunks → embed → replace_for_pdf
する Job 全体を mock で検証する。Docling chunk 抽出と Embedding は DI で差し替え可能。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx

from fujisawa_platform.crawler import PoliteFetcher, PoliteFetcherConfig
from fujisawa_platform.etl._repos.pdf_documents import PdfDocumentRecord
from fujisawa_platform.etl._runner import EtlRunResult
from fujisawa_platform.etl.pdf_archive import ArchivePut, LocalArchive
from fujisawa_platform.etl.yearly_navi import (
    NaviCrawlOutcome,
    crawl_and_index_navi,
    run_yearly_navi,
)
from fujisawa_platform.knowledge_base import MockEmbeddingClient
from fujisawa_platform.pdf_pipeline import PdfChunk

_PDF_URL = "https://www.city.fujisawa.kanagawa.jp/.../r8_navi0129.pdf"


def _stub_chunks() -> list[PdfChunk]:
    """Docling extract_chunks の戻り値を模す mock。"""
    return [
        PdfChunk(chunk_index=0, text="申込ナビ 第 1 章\n\n保育施設の概要。", page_number=1),
        PdfChunk(chunk_index=1, text="第 2 章 利用申込手順。", page_number=3),
        PdfChunk(chunk_index=2, text="第 3 章 選考基準。", page_number=19),
    ]


class _RecordingDocsRepo:
    def __init__(self) -> None:
        self.replaced: list[tuple[str, list[PdfDocumentRecord]]] = []

    async def replace_for_pdf(self, *, pdf_id: str, records: list[PdfDocumentRecord]) -> int:
        self.replaced.append((pdf_id, list(records)))
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


# ─────────────────────────────────────────────────────────────────────
# crawl_and_index_navi
# ─────────────────────────────────────────────────────────────────────


class TestCrawlAndIndexNavi:
    @pytest.mark.asyncio
    @respx.mock
    async def test_replaces_chunks_with_embedding(
        self, fetcher_config: PoliteFetcherConfig
    ) -> None:
        respx.get(_PDF_URL).mock(return_value=httpx.Response(200, content=b"%PDF-fake"))
        docs_repo = _RecordingDocsRepo()

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_index_navi(
                pdf_url=_PDF_URL,
                year=2026,
                fetcher=fetcher,
                repo=docs_repo,  # type: ignore[arg-type]
                embedder=MockEmbeddingClient(),
                chunk_extractor=lambda _: _stub_chunks(),
                now=lambda: datetime(2026, 5, 11, 0, 0, tzinfo=UTC),
            )

        # 3 chunk が replace される
        assert outcome.chunks_written == 3
        assert len(docs_repo.replaced) == 1
        pdf_id, records = docs_repo.replaced[0]
        # pdf_id は URL の SHA-256 hash
        assert len(pdf_id) == 64
        # chunk_index は 0..2 の連番
        assert [r.chunk_index for r in records] == [0, 1, 2]
        # 各 chunk の text / page_number / embedding 次元 / pdf_hash がセット済
        assert records[0].chunk_text.startswith("申込ナビ")
        assert records[0].page_number == 1
        assert len(records[0].embedding) == 768
        assert records[0].pdf_hash == records[1].pdf_hash  # 同じ PDF なので hash 一致
        assert all(r.url == _PDF_URL for r in records)

    @pytest.mark.asyncio
    @respx.mock
    async def test_dry_run_does_not_call_repo(
        self,
        tmp_path: Any,
        fetcher_config: PoliteFetcherConfig,
    ) -> None:
        respx.get(_PDF_URL).mock(return_value=httpx.Response(200, content=b"%PDF-fake"))
        archive = LocalArchive(root=tmp_path)
        docs_repo = _RecordingDocsRepo()

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_index_navi(
                pdf_url=_PDF_URL,
                year=2026,
                fetcher=fetcher,
                repo=docs_repo,  # type: ignore[arg-type]
                embedder=MockEmbeddingClient(),
                archive=archive,
                chunk_extractor=lambda _: _stub_chunks(),
                dry_run=True,
            )

        assert outcome.chunks_written == 3
        assert docs_repo.replaced == []  # DB は叩かない
        # 出典担保のため archive は実行される
        assert outcome.archive_path is not None
        assert await archive.exists(outcome.archive_path) is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_archive_called_before_parse(self, fetcher_config: PoliteFetcherConfig) -> None:
        respx.get(_PDF_URL).mock(return_value=httpx.Response(200, content=b"%PDF-fake"))
        archive = _RecordingArchive()

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_index_navi(
                pdf_url=_PDF_URL,
                year=2026,
                fetcher=fetcher,
                repo=_RecordingDocsRepo(),  # type: ignore[arg-type]
                embedder=MockEmbeddingClient(),
                archive=archive,  # type: ignore[arg-type]
                chunk_extractor=lambda _: _stub_chunks(),
            )

        assert len(archive.puts) == 1
        put = archive.puts[0]
        assert put["source_url"] == _PDF_URL
        assert outcome.archive_backend == "fake"
        assert outcome.archive_path is not None
        assert outcome.archive_path.startswith("yearly_navi_etl/2026/")

    @pytest.mark.asyncio
    @respx.mock
    async def test_zero_chunks_still_replaces(self, fetcher_config: PoliteFetcherConfig) -> None:
        """chunk 0 件でも replace_for_pdf は呼ぶ (古い chunk を残さない)。"""
        respx.get(_PDF_URL).mock(return_value=httpx.Response(200, content=b"%PDF-fake"))
        docs_repo = _RecordingDocsRepo()

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_index_navi(
                pdf_url=_PDF_URL,
                year=2026,
                fetcher=fetcher,
                repo=docs_repo,  # type: ignore[arg-type]
                embedder=MockEmbeddingClient(),
                chunk_extractor=lambda _: [],
            )

        assert outcome.chunks_written == 0
        assert len(docs_repo.replaced) == 1
        _, records = docs_repo.replaced[0]
        assert records == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_pdf_fetch_failure_propagates(self, fetcher_config: PoliteFetcherConfig) -> None:
        respx.get(_PDF_URL).mock(return_value=httpx.Response(404))

        async with PoliteFetcher(fetcher_config) as fetcher:
            with pytest.raises(httpx.HTTPStatusError):
                await crawl_and_index_navi(
                    pdf_url=_PDF_URL,
                    year=2026,
                    fetcher=fetcher,
                    repo=_RecordingDocsRepo(),  # type: ignore[arg-type]
                    embedder=MockEmbeddingClient(),
                    chunk_extractor=lambda _: _stub_chunks(),
                )


# ─────────────────────────────────────────────────────────────────────
# run_yearly_navi (Cloud Run Job entrypoint)
# ─────────────────────────────────────────────────────────────────────


class TestRunYearlyNavi:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_success_result(self, fetcher_config: PoliteFetcherConfig) -> None:
        respx.get(_PDF_URL).mock(return_value=httpx.Response(200, content=b"%PDF-fake"))
        runs = _FakeRunsRepo()

        result = await run_yearly_navi(
            pdf_url=_PDF_URL,
            year=2026,
            fetcher_config=fetcher_config,
            docs_repo=_RecordingDocsRepo(),  # type: ignore[arg-type]
            runs_repo=runs,  # type: ignore[arg-type]
            embedder=MockEmbeddingClient(),
            run_id="yearly_navi_etl-20260401-0300",
            chunk_extractor=lambda _: _stub_chunks(),
            now=lambda: datetime(2026, 5, 11, 0, 0, tzinfo=UTC),
        )

        assert isinstance(result, EtlRunResult)
        assert result.status == "success"
        assert result.rows_written == 3
        assert runs.finishes[0]["status"] == "success"


class TestNaviCrawlOutcomeModel:
    def test_frozen(self) -> None:
        outcome = NaviCrawlOutcome(
            chunks_written=3,
            pdf_hash="a" * 64,
            archive_path="yearly_navi_etl/2026/abc-r8_navi0129.pdf",
            archive_backend="local",
        )
        with pytest.raises(Exception):
            outcome.chunks_written = 99  # type: ignore[misc]
