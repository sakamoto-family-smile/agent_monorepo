"""EgovLawClient のテスト（httpx を MockTransport でスタブ化）。"""

from __future__ import annotations

import httpx
import pytest

from app.integrations.egov_law_client import (
    DEFAULT_EGOV_BASE_URL,
    EgovLawClient,
    EgovLawError,
)


def _build_mock_client(handler) -> httpx.AsyncClient:  # noqa: ANN001 — httpx handler
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, base_url="https://laws.e-gov.go.jp")


@pytest.mark.asyncio
async def test_fetch_law_text_success() -> None:
    expected = "<Law>...</Law>"

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/api/2/law_data/335AC0000000105" in request.url.path
        return httpx.Response(200, text=expected)

    egov = EgovLawClient(client=_build_mock_client(handler))
    text = await egov.fetch_law_text("335AC0000000105")
    assert text == expected


@pytest.mark.asyncio
async def test_fetch_law_text_raises_on_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(404, text="not found")

    egov = EgovLawClient(client=_build_mock_client(handler))
    with pytest.raises(EgovLawError, match="status=404"):
        await egov.fetch_law_text("nonexistent")


@pytest.mark.asyncio
async def test_fetch_law_text_raises_on_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        raise httpx.ConnectError("connection refused")

    egov = EgovLawClient(client=_build_mock_client(handler))
    with pytest.raises(EgovLawError, match="e-Gov fetch failed"):
        await egov.fetch_law_text("335AC0000000105")


@pytest.mark.asyncio
async def test_health_check_returns_true_on_2xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/swagger.json")
        return httpx.Response(200, text="{}")

    egov = EgovLawClient(client=_build_mock_client(handler))
    assert await egov.health_check() is True


@pytest.mark.asyncio
async def test_health_check_returns_false_on_5xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(503, text="")

    egov = EgovLawClient(client=_build_mock_client(handler))
    assert await egov.health_check() is False


@pytest.mark.asyncio
async def test_health_check_returns_false_on_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        raise httpx.ConnectError("connection refused")

    egov = EgovLawClient(client=_build_mock_client(handler))
    assert await egov.health_check() is False


def test_default_base_url_is_egov() -> None:
    """ハードコードされた base_url が e-Gov v2 を指している。"""
    assert "laws.e-gov.go.jp/api/2" in DEFAULT_EGOV_BASE_URL
