"""line-bot: 本番 (ENV=gcp / Cloud Run) で /docs・/redoc・/openapi.json が無効化されることのテスト。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


@pytest.fixture(autouse=True)
def _clear_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("ENABLE_API_DOCS", raising=False)
    monkeypatch.delenv("ENV", raising=False)


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    import app.main as main_module
    from app.config import Settings

    monkeypatch.setattr(main_module, "settings", Settings(_env_file=None))
    # lifespan は起動しない (with 構文を使わない) ので pool 初期化等は走らない
    return TestClient(main_module.create_app())


def test_docs_enabled_in_local_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "local")
    client = _client(monkeypatch)
    for path in DOC_PATHS:
        assert client.get(path).status_code == 200, path


def test_docs_disabled_in_gcp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "gcp")
    client = _client(monkeypatch)
    for path in DOC_PATHS:
        assert client.get(path).status_code == 404, path


def test_docs_disabled_on_cloud_run_even_if_env_is_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ENV の設定漏れがあっても Cloud Run (K_SERVICE あり) なら公開しない。"""
    monkeypatch.setenv("ENV", "local")
    monkeypatch.setenv("K_SERVICE", "driving-license-bot-line")
    client = _client(monkeypatch)
    for path in DOC_PATHS:
        assert client.get(path).status_code == 404, path


def test_docs_enabled_by_explicit_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "gcp")
    monkeypatch.setenv("ENABLE_API_DOCS", "true")
    client = _client(monkeypatch)
    for path in DOC_PATHS:
        assert client.get(path).status_code == 200, path
