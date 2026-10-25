"""本番 (Cloud Run) で FastAPI の /docs・/redoc・/openapi.json が無効化されることのテスト。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


@pytest.fixture(autouse=True)
def _clear_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("FUJISAWA_INFO_BOT_ENABLE_API_DOCS", raising=False)


def _client() -> TestClient:
    # lifespan を起動しない (with 構文を使わない) ので LLM / KB 初期化は走らない
    return TestClient(create_app(Settings()))


def test_docs_enabled_outside_cloud_run() -> None:
    client = _client()
    for path in DOC_PATHS:
        assert client.get(path).status_code == 200, path


def test_docs_disabled_on_cloud_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("K_SERVICE", "fujisawa-info-bot")
    client = _client()
    for path in DOC_PATHS:
        assert client.get(path).status_code == 404, path
    # 業務 endpoint は影響を受けない
    assert client.get("/health").status_code == 200


def test_docs_enabled_by_explicit_flag_on_cloud_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("K_SERVICE", "fujisawa-info-bot")
    monkeypatch.setenv("FUJISAWA_INFO_BOT_ENABLE_API_DOCS", "true")
    client = _client()
    for path in DOC_PATHS:
        assert client.get(path).status_code == 200, path
