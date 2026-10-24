"""本番では認証のない旧 Web API と /docs をマウントしないことの確認。

FastAPI のバージョンで `app.routes` の構造が変わるため、ルート一覧ではなく
実際のリクエストに対するレスポンス (404 か否か) で判定する。リクエストボディは
不正にしてあり、マウントされていても 4xx/5xx で返るだけで副作用はない。
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import config


def _client(monkeypatch, *, app_env: str, env: dict[str, str]) -> TestClient:
    import main

    monkeypatch.setattr(config.settings, "app_env", app_env)
    for k in ("ENABLE_WEB_API", "ENABLE_API_DOCS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    reloaded = importlib.reload(main)
    # `with` を使わない = lifespan (DB 初期化等) を走らせない
    return TestClient(reloaded.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _restore_main(monkeypatch):
    yield
    monkeypatch.undo()
    import main

    importlib.reload(main)


def _web_api_mounted(c: TestClient) -> bool:
    statuses = [
        c.post("/api/analyze", json={}).status_code,
        c.post("/api/resolve-ticker", json={}).status_code,
        c.post("/api/screen", content=b"not-json").status_code,
    ]
    mounted = [s != 404 for s in statuses]
    assert len(set(mounted)) == 1, statuses  # 全部マウント or 全部なし
    return mounted[0]


def _docs_mounted(c: TestClient) -> bool:
    statuses = [c.get(p).status_code for p in ("/docs", "/redoc", "/openapi.json")]
    assert len({s == 200 for s in statuses}) == 1, statuses
    return statuses[0] == 200


def test_prod_hides_web_api_and_docs(monkeypatch):
    c = _client(monkeypatch, app_env="prod", env={})
    assert not _web_api_mounted(c)
    assert not _docs_mounted(c)
    # LINE webhook / worker / health は残る
    assert c.post("/api/line/webhook", content=b"{}").status_code != 404
    assert c.post("/api/tasks/analyze", json={}).status_code != 404
    assert c.get("/health").status_code == 200


def test_local_keeps_web_api_and_docs(monkeypatch):
    c = _client(monkeypatch, app_env="local", env={})
    assert _web_api_mounted(c)
    assert _docs_mounted(c)


def test_prod_can_opt_in(monkeypatch):
    c = _client(
        monkeypatch, app_env="prod", env={"ENABLE_WEB_API": "true", "ENABLE_API_DOCS": "true"}
    )
    assert _web_api_mounted(c)
    assert _docs_mounted(c)
