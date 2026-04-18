"""/api/profile — 世帯プロファイル CRUD の統合テスト。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# --- Members -----------------------------------------------------------------


async def test_list_members_empty(client):
    r = await client.get("/api/profile/members")
    assert r.status_code == 200
    assert r.json() == []


async def test_create_and_list_member(client):
    payload = {
        "name": "太郎",
        "relation": "owner",
        "birth_date": "1988-04-01",
        "employment_status": "employed",
        "annual_income": "6000000",
        "note": "世帯主",
    }
    r = await client.post("/api/profile/members", json=payload)
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "太郎"
    assert body["relation"] == "owner"
    assert body["annual_income"] == "6000000"

    r = await client.get("/api/profile/members")
    assert r.status_code == 200
    assert len(r.json()) == 1


async def test_invalid_relation_rejected(client):
    payload = {"name": "X", "relation": "boss"}
    r = await client.post("/api/profile/members", json=payload)
    assert r.status_code == 422


async def test_negative_income_rejected(client):
    payload = {"name": "X", "relation": "owner", "annual_income": "-1"}
    r = await client.post("/api/profile/members", json=payload)
    assert r.status_code == 422


async def test_delete_member(client):
    payload = {"name": "child", "relation": "child"}
    r = await client.post("/api/profile/members", json=payload)
    member_id = r.json()["id"]

    r = await client.delete(f"/api/profile/members/{member_id}")
    assert r.status_code == 204

    r = await client.delete(f"/api/profile/members/{member_id}")
    assert r.status_code == 404


# --- Assets ------------------------------------------------------------------


async def test_create_and_list_asset(client):
    payload = {
        "kind": "deposit",
        "name": "A銀行普通預金",
        "value": "3000000",
        "as_of": "2026-04-01",
        "note": "給与口座",
    }
    r = await client.post("/api/profile/assets", json=payload)
    assert r.status_code == 201
    assert r.json()["kind"] == "deposit"

    r = await client.get("/api/profile/assets")
    assert len(r.json()) == 1


async def test_delete_asset(client):
    r = await client.post(
        "/api/profile/assets",
        json={"kind": "cash", "name": "現金", "value": "100000", "as_of": "2026-04-01"},
    )
    asset_id = r.json()["id"]
    r = await client.delete(f"/api/profile/assets/{asset_id}")
    assert r.status_code == 204


async def test_invalid_asset_kind_rejected(client):
    r = await client.post(
        "/api/profile/assets",
        json={"kind": "crypto", "name": "BTC", "value": "100", "as_of": "2026-04-01"},
    )
    assert r.status_code == 422


# --- Liabilities -------------------------------------------------------------


async def test_create_and_list_liability(client):
    payload = {
        "kind": "mortgage",
        "name": "住宅ローン",
        "balance": "30000000",
        "interest_rate": "0.0075",
        "as_of": "2026-04-01",
    }
    r = await client.post("/api/profile/liabilities", json=payload)
    assert r.status_code == 201
    assert r.json()["kind"] == "mortgage"

    r = await client.get("/api/profile/liabilities")
    assert len(r.json()) == 1


async def test_negative_balance_rejected(client):
    r = await client.post(
        "/api/profile/liabilities",
        json={
            "kind": "car_loan",
            "name": "車",
            "balance": "-100",
            "interest_rate": "0.03",
            "as_of": "2026-04-01",
        },
    )
    assert r.status_code == 422


async def test_interest_rate_above_100pct_rejected(client):
    r = await client.post(
        "/api/profile/liabilities",
        json={
            "kind": "credit_card",
            "name": "カード",
            "balance": "50000",
            "interest_rate": "1.5",
            "as_of": "2026-04-01",
        },
    )
    assert r.status_code == 422


async def test_delete_liability(client):
    r = await client.post(
        "/api/profile/liabilities",
        json={
            "kind": "other",
            "name": "一時",
            "balance": "1000",
            "interest_rate": "0",
            "as_of": "2026-04-01",
        },
    )
    liab_id = r.json()["id"]
    r = await client.delete(f"/api/profile/liabilities/{liab_id}")
    assert r.status_code == 204
