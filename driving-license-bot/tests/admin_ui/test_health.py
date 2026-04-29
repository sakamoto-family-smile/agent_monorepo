"""GET /healthz は IAP 認証なしで 200 を返すべき（Cloud Run の liveness probe 用）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """ADMIN_DEV_BYPASS=true で固定 dev email を返す状態にする。"""
    from importlib import reload

    monkeypatch.setenv("ADMIN_DEV_BYPASS", "true")
    monkeypatch.setenv("ADMIN_ALLOWED_EMAILS", "")
    import review_admin_ui.config as config_module

    reload(config_module)
    import review_admin_ui.main as main_module

    reload(main_module)
    return TestClient(main_module.app)


def test_healthz_returns_ok(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "service" in body
    assert "version" in body


def test_healthz_no_auth_required(client: TestClient) -> None:
    """IAP header を付けなくても 200。"""
    resp = client.get("/healthz")
    assert resp.status_code == 200
