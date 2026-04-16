import pytest
from httpx import AsyncClient, ASGITransport
import sys
import os

# Add app to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

# Override settings for testing before importing app
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("DB_PATH", ":memory:")
os.environ.setdefault("DATA_DIR", "/tmp/test_stock_data")


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CHARTS_DIR", str(tmp_path / "charts"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("DICTIONARIES_DIR", str(tmp_path / "dictionaries"))


@pytest.mark.asyncio
async def test_health(setup_test_env):
    # Import after env setup
    import importlib
    import config
    importlib.reload(config)

    from main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "stock-analysis-agent"
