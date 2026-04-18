"""/api/scenarios と /api/scenarios/{id}/simulate のルート統合テスト。"""

from __future__ import annotations

from decimal import Decimal

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
def scenario_payload() -> dict:
    return {
        "name": "Baseline",
        "description": "30年ベースラインシナリオ",
        "primary_salary": "6000000",
        "spouse_salary": "3000000",
        "base_annual_expense": "4200000",
        "initial_net_worth": "5000000",
        "start_year": 2026,
        "horizon_years": 30,
        "salary_growth_rate": "0.01",
        "inflation_rate": "0.01",
        "investment_return_rate": "0.02",
    }


async def test_list_scenarios_empty(client):
    r = await client.get("/api/scenarios")
    assert r.status_code == 200
    assert r.json() == []


async def test_create_and_get_scenario(client, scenario_payload):
    r = await client.post("/api/scenarios", json=scenario_payload)
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Baseline"
    assert body["household_id"] == "test-household"
    assert body["base_assumptions"]["primary_salary"] == "6000000"

    # GET でも取得できる
    scenario_id = body["id"]
    r = await client.get(f"/api/scenarios/{scenario_id}")
    assert r.status_code == 200
    assert r.json()["id"] == scenario_id


async def test_get_scenario_not_found(client):
    r = await client.get("/api/scenarios/9999")
    assert r.status_code == 404


async def test_add_event_to_scenario(client, scenario_payload):
    r = await client.post("/api/scenarios", json=scenario_payload)
    scenario_id = r.json()["id"]
    event_payload = {
        "event_type": "E01",
        "start_year": 2027,
        "params": {
            "birth_year": 2027,
            "parental_leave_parent_salary": "4800000",
            "household_income_for_childcare": "9000000",
        },
    }
    r = await client.post(f"/api/scenarios/{scenario_id}/events", json=event_payload)
    assert r.status_code == 201
    body = r.json()
    assert body["event_type"] == "E01"
    assert body["start_year"] == 2027

    r = await client.get(f"/api/scenarios/{scenario_id}/events")
    assert r.status_code == 200
    assert len(r.json()) == 1


async def test_invalid_event_type(client, scenario_payload):
    r = await client.post("/api/scenarios", json=scenario_payload)
    scenario_id = r.json()["id"]
    r = await client.post(
        f"/api/scenarios/{scenario_id}/events",
        json={"event_type": "invalid", "start_year": 2027, "params": {}},
    )
    assert r.status_code == 422


async def test_simulate_baseline(client, scenario_payload):
    """イベント無しのベースラインで 30 年回る。"""
    r = await client.post("/api/scenarios", json=scenario_payload)
    scenario_id = r.json()["id"]

    r = await client.post(f"/api/scenarios/{scenario_id}/simulate")
    assert r.status_code == 200
    body = r.json()
    assert body["horizon_years"] == 30
    assert len(body["rows"]) == 30
    assert body["rows"][0]["year"] == 2026
    assert body["rows"][-1]["year"] == 2055
    # 純資産は初期値より増えている(手取 > 生活費)
    assert Decimal(body["total_net_worth_end"]) > Decimal("5000000")


async def test_simulate_with_birth_event(client, scenario_payload):
    """出産イベント付きのシミュはイベント差分が負になる。"""
    r = await client.post("/api/scenarios", json=scenario_payload)
    scenario_id = r.json()["id"]
    await client.post(
        f"/api/scenarios/{scenario_id}/events",
        json={
            "event_type": "E01",
            "start_year": 2027,
            "params": {
                "birth_year": 2027,
                "parental_leave_parent_salary": "4800000",
                "household_income_for_childcare": "9000000",
            },
        },
    )
    r = await client.post(f"/api/scenarios/{scenario_id}/simulate")
    assert r.status_code == 200
    body = r.json()
    # イベント差分は負(教育費 > 児童手当+育休)
    assert Decimal(body["total_event_net"]) < Decimal(0)


async def test_simulate_not_found(client):
    r = await client.post("/api/scenarios/9999/simulate")
    assert r.status_code == 404


async def test_invalid_salary_rejected(client, scenario_payload):
    bad = dict(scenario_payload)
    bad["primary_salary"] = "-1"
    r = await client.post("/api/scenarios", json=bad)
    assert r.status_code == 422
