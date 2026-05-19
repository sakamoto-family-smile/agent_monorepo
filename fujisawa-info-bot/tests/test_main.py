"""Phase 0 雛形の smoke test。 `/health` endpoint が 200 / `{status: ok}` を返すこと。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


class TestHealthEndpoint:
    def test_returns_ok(self) -> None:
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_app_metadata(self) -> None:
        """OpenAPI metadata が proposal 0004 で想定する agent 名を反映していること。"""
        assert app.title == "fujisawa-info-bot"
        assert app.version == "0.1.0"
