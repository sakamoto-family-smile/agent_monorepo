"""本番相当環境で FastAPI の /docs・/redoc・/openapi.json が無効化されることのテスト。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


def _build_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    import config
    import main

    monkeypatch.setattr(main, "settings", config.Settings())
    # lifespan は起動しない (with 構文を使わない) ので DB 初期化は走らない
    return TestClient(main.create_app())


@pytest.fixture(autouse=True)
def _clear_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("ENABLE_API_DOCS", raising=False)


@pytest.mark.parametrize("app_env", ["dev", "local", "test"])
def test_docs_enabled_in_local_env(monkeypatch: pytest.MonkeyPatch, app_env: str) -> None:
    monkeypatch.setenv("APP_ENV", app_env)
    client = _build_client(monkeypatch)
    for path in DOC_PATHS:
        assert client.get(path).status_code == 200, path


@pytest.mark.parametrize("app_env", ["prod", "production", "gcp", "staging"])
def test_docs_disabled_in_production_env(monkeypatch: pytest.MonkeyPatch, app_env: str) -> None:
    monkeypatch.setenv("APP_ENV", app_env)
    client = _build_client(monkeypatch)
    for path in DOC_PATHS:
        assert client.get(path).status_code == 404, path


def test_docs_disabled_on_cloud_run_even_if_app_env_is_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """APP_ENV の設定漏れがあっても Cloud Run (K_SERVICE あり) なら公開しない。"""
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("K_SERVICE", "piyolog-analytics")
    client = _build_client(monkeypatch)
    for path in DOC_PATHS:
        assert client.get(path).status_code == 404, path


def test_docs_enabled_by_explicit_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("K_SERVICE", "piyolog-analytics")
    monkeypatch.setenv("ENABLE_API_DOCS", "true")
    client = _build_client(monkeypatch)
    for path in DOC_PATHS:
        assert client.get(path).status_code == 200, path
