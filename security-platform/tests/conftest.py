"""Shared pytest fixtures for the Agent Security Platform test suite."""
from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base


pytest_plugins = ["anyio"]


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def tmp_db_url(tmp_path_factory):
    """Create a temporary SQLite database URL, initialize it, and yield."""
    tmp_dir = tmp_path_factory.mktemp("db")
    db_path = tmp_dir / "test_security.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"
    return db_url


@pytest.fixture
def gateway_client(monkeypatch):
    """TestClient for the MCP gateway FastAPI app."""
    monkeypatch.setenv("MCP_TARGET_URL", "http://localhost:19999")

    # Import after setting env vars so server picks up the target URL
    from src.proxy import server as server_module

    # Reset global mode to passive before each test
    server_module._gateway_mode = "passive"

    with TestClient(server_module.app) as client:
        yield client

    # Restore passive mode after test
    server_module._gateway_mode = "passive"
