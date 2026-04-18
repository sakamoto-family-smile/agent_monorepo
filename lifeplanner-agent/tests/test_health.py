import os

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MF_CSV_DIR", str(tmp_path / "mf_csv"))


@pytest.mark.asyncio
async def test_health_returns_ok():
    import importlib
    import config
    importlib.reload(config)
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data == {"status": "ok", "service": "lifeplanner-agent"}
