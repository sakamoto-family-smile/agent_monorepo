"""EdinetClient のテスト (respx で EDINET API を mock)。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from edinet_client import (
    DocumentMetadata,
    DocumentType,
    EdinetClient,
    InMemoryCache,
)

_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_index() -> dict:
    return json.loads((_FIXTURES / "documents_index_sample.json").read_text())


@pytest.fixture
def cache() -> InMemoryCache:
    return InMemoryCache()


class TestListDocuments:
    @pytest.mark.asyncio
    @respx.mock
    async def test_normalizes_response_to_pydantic(
        self, sample_index: dict, cache: InMemoryCache
    ) -> None:
        route = respx.get("https://api.edinet-fsa.go.jp/api/v2/documents.json").mock(
            return_value=httpx.Response(200, json=sample_index),
        )
        async with EdinetClient(api_key="test-key", cache=cache, min_interval_sec=0.001) as client:
            docs = await client.list_documents(date(2026, 5, 22))

        assert route.called
        assert len(docs) == 3
        toyota = docs[0]
        assert isinstance(toyota, DocumentMetadata)
        assert toyota.document_id == "S100ABC1"
        assert toyota.edinet_code == "E02144"
        assert toyota.securities_code == "72030"
        assert toyota.submitter_name == "トヨタ自動車株式会社"
        assert toyota.document_type == DocumentType.ANNUAL_REPORT
        assert toyota.submit_date == date(2026, 5, 22)
        assert toyota.period_end == date(2026, 3, 31)
        assert toyota.xbrl_flag is True
        assert toyota.pdf_flag is True
        assert toyota.attach_doc_flag is True
        assert toyota.is_available is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_withdrawn_document_marked_unavailable(
        self, sample_index: dict, cache: InMemoryCache
    ) -> None:
        respx.get("https://api.edinet-fsa.go.jp/api/v2/documents.json").mock(
            return_value=httpx.Response(200, json=sample_index),
        )
        async with EdinetClient(api_key="test-key", cache=cache, min_interval_sec=0.001) as client:
            docs = await client.list_documents(date(2026, 5, 22))

        # 3 つ目の大量保有報告書は withdrawalStatus=1
        major_holding = docs[2]
        assert major_holding.document_id == "S100GHI3"
        assert major_holding.withdrawal_status == 1
        assert major_holding.is_available is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_response(self, cache: InMemoryCache) -> None:
        respx.get("https://api.edinet-fsa.go.jp/api/v2/documents.json").mock(
            return_value=httpx.Response(
                200, json={"metadata": {}, "results": []}
            ),
        )
        async with EdinetClient(api_key="test-key", cache=cache, min_interval_sec=0.001) as client:
            docs = await client.list_documents(date(2026, 5, 22))

        assert docs == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_unknown_doc_type_kept_as_str(self, cache: InMemoryCache) -> None:
        respx.get("https://api.edinet-fsa.go.jp/api/v2/documents.json").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "docID": "S100UNKNOWN",
                            "edinetCode": "E99999",
                            "secCode": None,
                            "filerName": "未知の提出者",
                            "docTypeCode": "999",
                            "submitDateTime": "2026-05-22 10:00",
                            "docDescription": "未知書類",
                            "withdrawalStatus": "0",
                            "disclosureStatus": "0",
                            "docInfoEditStatus": "0",
                            "xbrlFlag": "0",
                            "pdfFlag": "0",
                            "attachDocFlag": "0",
                        }
                    ]
                },
            ),
        )
        async with EdinetClient(api_key="test-key", cache=cache, min_interval_sec=0.001) as client:
            docs = await client.list_documents(date(2026, 5, 22))

        assert len(docs) == 1
        # 未知コードは str のまま保持
        assert docs[0].document_type == "999"


class TestDownload:
    @pytest.mark.asyncio
    @respx.mock
    async def test_pdf_download_caches_payload(self, cache: InMemoryCache) -> None:
        respx.get("https://api.edinet-fsa.go.jp/api/v2/documents/S100ABC1").mock(
            return_value=httpx.Response(200, content=b"%PDF-1.4 fake content"),
        )
        async with EdinetClient(api_key="test-key", cache=cache, min_interval_sec=0.001) as client:
            body = await client.download("S100ABC1", content_type="pdf")

        assert body.document_id == "S100ABC1"
        assert body.content_type == "pdf"
        assert body.bytes_payload == b"%PDF-1.4 fake content"
        assert body.from_cache is False

        # 2 回目は cache 命中
        cached = await cache.get("S100ABC1", "pdf")
        assert cached == b"%PDF-1.4 fake content"

    @pytest.mark.asyncio
    @respx.mock
    async def test_second_download_hits_cache(self, cache: InMemoryCache) -> None:
        route = respx.get(
            "https://api.edinet-fsa.go.jp/api/v2/documents/S100ABC1"
        ).mock(return_value=httpx.Response(200, content=b"first call"))

        async with EdinetClient(api_key="test-key", cache=cache, min_interval_sec=0.001) as client:
            first = await client.download("S100ABC1", content_type="pdf")
            second = await client.download("S100ABC1", content_type="pdf")

        assert first.from_cache is False
        assert second.from_cache is True
        assert second.bytes_payload == b"first call"
        assert route.call_count == 1  # 2 回目は HTTP を打たない

    @pytest.mark.asyncio
    @respx.mock
    async def test_xbrl_zip_uses_type_1(self, cache: InMemoryCache) -> None:
        route = respx.get(
            "https://api.edinet-fsa.go.jp/api/v2/documents/S100ABC1",
        ).mock(return_value=httpx.Response(200, content=b"PK\x03\x04 fake zip"))

        async with EdinetClient(api_key="test-key", cache=cache, min_interval_sec=0.001) as client:
            body = await client.download("S100ABC1", content_type="xbrl_zip")

        assert body.bytes_payload.startswith(b"PK")
        # type=1 が URL クエリに含まれることを確認
        assert "type=1" in str(route.calls[0].request.url)


class TestRetryAndRateLimit:
    @pytest.mark.asyncio
    @respx.mock
    async def test_5xx_retried_then_succeeds(self, cache: InMemoryCache) -> None:
        responses = [
            httpx.Response(500, json={"error": "server"}),
            httpx.Response(500, json={"error": "server"}),
            httpx.Response(200, json={"results": []}),
        ]
        respx.get("https://api.edinet-fsa.go.jp/api/v2/documents.json").mock(
            side_effect=responses,
        )
        async with EdinetClient(
            api_key="test-key", cache=cache, min_interval_sec=0.001, max_retries=3
        ) as client:
            docs = await client.list_documents(date(2026, 5, 22))

        assert docs == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_4xx_raises_immediately(self, cache: InMemoryCache) -> None:
        respx.get("https://api.edinet-fsa.go.jp/api/v2/documents.json").mock(
            return_value=httpx.Response(403, json={"error": "forbidden"}),
        )
        async with EdinetClient(
            api_key="test-key", cache=cache, min_interval_sec=0.001, max_retries=3
        ) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await client.list_documents(date(2026, 5, 22))

    @pytest.mark.asyncio
    @respx.mock
    async def test_429_treated_as_retryable(self, cache: InMemoryCache) -> None:
        responses = [
            httpx.Response(429, json={"error": "rate"}),
            httpx.Response(200, json={"results": []}),
        ]
        respx.get("https://api.edinet-fsa.go.jp/api/v2/documents.json").mock(
            side_effect=responses,
        )
        async with EdinetClient(
            api_key="test-key", cache=cache, min_interval_sec=0.001, max_retries=2
        ) as client:
            docs = await client.list_documents(date(2026, 5, 22))

        assert docs == []


class TestInitValidation:
    def test_empty_api_key_rejected(self, cache: InMemoryCache) -> None:
        with pytest.raises(ValueError, match="api_key"):
            EdinetClient(api_key="", cache=cache)

    @pytest.mark.asyncio
    async def test_request_outside_context_manager_raises(
        self, cache: InMemoryCache
    ) -> None:
        client = EdinetClient(api_key="key", cache=cache)
        with pytest.raises(RuntimeError, match="async context manager"):
            await client.list_documents(date(2026, 5, 22))
