"""HTTP ルートの統合テスト (healthz / recipes / inventory)。"""

from __future__ import annotations

import importlib

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANALYTICS_DATA_DIR", str(tmp_path / "analytics"))
    # menu-catalog は実 JSON を使う (Phase 1 シード)


@pytest.fixture
async def client():
    import config
    importlib.reload(config)
    import instrumentation
    instrumentation.reset_for_tests()
    instrumentation.setup_observability()

    from services import database, menu_catalog
    menu_catalog.reset_for_tests()
    await database.init_db()

    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await instrumentation.shutdown_observability()


# ---------------------------------------------------------------------------
# /healthz
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_healthz_returns_ok(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body == {"status": "ok", "service": "hotcook-agent"}


# ---------------------------------------------------------------------------
# /api/recipes/suggest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggest_returns_200_with_candidates(client):
    r = await client.post(
        "/api/recipes/suggest",
        json={
            "ingredients": [
                {"name": "じゃがいも"},
                {"name": "牛肉"},
                {"name": "玉ねぎ"},
            ],
            "top_n": 3,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "candidates" in body
    assert "disclaimer" in body
    assert "suggested_at" in body
    assert len(body["candidates"]) > 0
    names = [c["name"] for c in body["candidates"]]
    assert "肉じゃが" in names


@pytest.mark.asyncio
async def test_suggest_validates_empty_ingredients(client):
    r = await client.post(
        "/api/recipes/suggest",
        json={"ingredients": [], "top_n": 5},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_suggest_returns_fallback_hint_when_no_match(client):
    r = await client.post(
        "/api/recipes/suggest",
        json={"ingredients": [{"name": "謎食材"}], "top_n": 5},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["candidates"] == []
    assert body["fallback_hint"]


@pytest.mark.asyncio
async def test_suggest_respects_max_cook_minutes(client):
    r = await client.post(
        "/api/recipes/suggest",
        json={
            "ingredients": [{"name": "豚肉"}, {"name": "大根"}],
            "top_n": 10,
            "max_cook_minutes": 30,
        },
    )
    assert r.status_code == 200
    for c in r.json()["candidates"]:
        assert c["cook_minutes"] <= 30


@pytest.mark.asyncio
async def test_suggest_records_history_in_sqlite(client, tmp_path):
    # 1 回提案を打った後、SQLite に履歴が入っていることを確認
    await client.post(
        "/api/recipes/suggest",
        json={
            "ingredients": [{"name": "じゃがいも"}, {"name": "玉ねぎ"}],
            "top_n": 3,
        },
    )

    import aiosqlite
    db_path = str(tmp_path / "test.db")
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT count(*) FROM suggestion_history")
        row = await cursor.fetchone()
    assert row is not None
    assert row[0] >= 1


# ---------------------------------------------------------------------------
# /api/inventory CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inventory_full_lifecycle(client):
    # initially empty
    r = await client.get("/api/inventory")
    assert r.status_code == 200
    assert r.json()["total"] == 0

    # create
    r = await client.post(
        "/api/inventory",
        json={"name": "じゃがいも", "quantity": 3, "unit": "個", "expires_on": "2026-05-01"},
    )
    assert r.status_code == 201
    item_id = r.json()["id"]
    assert item_id is not None

    # list
    r = await client.get("/api/inventory")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "じゃがいも"

    # update
    r = await client.put(
        f"/api/inventory/{item_id}",
        json={"name": "じゃがいも", "quantity": 5, "unit": "個", "expires_on": "2026-05-05"},
    )
    assert r.status_code == 200
    assert r.json()["quantity"] == 5

    # delete
    r = await client.delete(f"/api/inventory/{item_id}")
    assert r.status_code == 200
    assert r.json() == {"deleted": item_id}

    # verify gone
    r = await client.get("/api/inventory")
    assert r.json()["total"] == 0


@pytest.mark.asyncio
async def test_inventory_update_missing_returns_404(client):
    r = await client.put(
        "/api/inventory/99999",
        json={"name": "x", "quantity": 1, "unit": "個"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_inventory_delete_missing_returns_404(client):
    r = await client.delete("/api/inventory/99999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_inventory_list_limit_validated(client):
    r = await client.get("/api/inventory?limit=0")
    assert r.status_code == 422
    r = await client.get("/api/inventory?limit=999999")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_inventory_sorted_by_expires_on_then_updated(client):
    # 3 件を異なる expires_on で投入し、近い順に並ぶことを確認
    for name, exp in [("Aだいこん", "2026-12-01"), ("Bほうれん草", "2026-04-25"), ("Cきゃべつ", None)]:
        await client.post(
            "/api/inventory",
            json={"name": name, "quantity": 1, "unit": "個", "expires_on": exp},
        )

    r = await client.get("/api/inventory")
    items = r.json()["items"]
    # expires_on が近い順 → None は最後
    assert items[0]["name"] == "Bほうれん草"
    assert items[1]["name"] == "Aだいこん"
    assert items[2]["name"] == "Cきゃべつ"
