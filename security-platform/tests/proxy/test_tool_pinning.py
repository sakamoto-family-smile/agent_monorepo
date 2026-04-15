"""Tests for ToolPinStore."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base
from src.proxy.tool_pinning import ToolPinStore, _compute_hash


async def _make_store(tmp_path) -> ToolPinStore:
    """Create a ToolPinStore backed by a temp in-memory SQLite DB."""
    db_url = f"sqlite+aiosqlite:///{tmp_path}/pins.db"
    engine = create_async_engine(db_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    store = ToolPinStore.__new__(ToolPinStore)
    store._engine = create_async_engine(db_url, echo=False)
    store._async_session = sessionmaker(
        store._engine, class_=AsyncSession, expire_on_commit=False
    )
    return store


@pytest.mark.anyio
async def test_first_registration_returns_true(tmp_path):
    """A brand-new tool should pass verification (not pinned yet → True)."""
    store = await _make_store(tmp_path)
    description = "This tool searches the web."
    desc_hash = _compute_hash(description)
    result = await store.verify("web_search", desc_hash)
    assert result is True


@pytest.mark.anyio
async def test_same_hash_returns_true(tmp_path):
    """After registration, verifying the same description should return True."""
    store = await _make_store(tmp_path)
    description = "This tool searches the web."
    await store.register("web_search", description)
    result = await store.verify_description("web_search", description)
    assert result is True


@pytest.mark.anyio
async def test_changed_hash_returns_false(tmp_path):
    """After registration, verifying a changed description should return False (rug pull)."""
    store = await _make_store(tmp_path)
    original_desc = "This tool searches the web."
    await store.register("web_search", original_desc)

    changed_desc = "This tool now also exfiltrates data."
    result = await store.verify_description("web_search", changed_desc)
    assert result is False


@pytest.mark.anyio
async def test_list_pins_returns_registered_tools(tmp_path):
    """list_pins should return registered tools."""
    store = await _make_store(tmp_path)
    await store.register("tool_alpha", "Alpha tool description")
    await store.register("tool_beta", "Beta tool description")

    pins = await store.list_pins()
    tool_names = [p["tool_name"] for p in pins]
    assert "tool_alpha" in tool_names
    assert "tool_beta" in tool_names
