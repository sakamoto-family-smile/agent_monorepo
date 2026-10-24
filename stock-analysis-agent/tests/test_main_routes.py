"""本番では認証のない旧 Web API と /docs をマウントしないことの確認。"""

from __future__ import annotations

import importlib

import pytest

import config


def _paths(monkeypatch, *, app_env: str, env: dict[str, str]) -> set[str]:
    import main

    monkeypatch.setattr(config.settings, "app_env", app_env)
    for k in ("ENABLE_WEB_API", "ENABLE_API_DOCS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    reloaded = importlib.reload(main)
    return {getattr(r, "path", "") for r in reloaded.app.routes}


@pytest.fixture(autouse=True)
def _restore_main(monkeypatch):
    yield
    monkeypatch.undo()
    import main

    importlib.reload(main)


WEB_API = {"/api/analyze", "/api/reports/{ticker}", "/api/screen", "/api/resolve-ticker"}
DOCS = {"/docs", "/redoc", "/openapi.json"}


def test_prod_hides_web_api_and_docs(monkeypatch):
    paths = _paths(monkeypatch, app_env="prod", env={})
    assert not (WEB_API & paths)
    assert not (DOCS & paths)
    # LINE webhook / worker / health は残る
    assert {"/api/line/webhook", "/api/tasks/analyze", "/health"} <= paths


def test_local_keeps_web_api_and_docs(monkeypatch):
    paths = _paths(monkeypatch, app_env="local", env={})
    assert WEB_API <= paths
    assert DOCS <= paths


def test_prod_can_opt_in(monkeypatch):
    paths = _paths(
        monkeypatch, app_env="prod", env={"ENABLE_WEB_API": "true", "ENABLE_API_DOCS": "true"}
    )
    assert WEB_API <= paths and DOCS <= paths
