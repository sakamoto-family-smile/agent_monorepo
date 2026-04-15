"""Health endpoint smoke test."""
import os
import pytest
from httpx import AsyncClient, ASGITransport

# Firebase を初期化しないようにエミュレーター設定
os.environ.setdefault("FIREBASE_AUTH_EMULATOR_HOST", "localhost:9099")
os.environ.setdefault("FIREBASE_PROJECT_ID", "demo-kanie-lab")
os.environ.setdefault("APP_ENV", "local")


@pytest.fixture
def app():
    # Firebase Admin SDK をモックしてインポート
    import unittest.mock as mock
    with mock.patch("firebase_admin.initialize_app"), \
         mock.patch("firebase_admin._apps", {}):
        from main import app
        return app


@pytest.mark.anyio
async def test_health(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "kanie-lab-backend"
