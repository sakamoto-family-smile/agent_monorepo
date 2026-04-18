"""/api/scenarios/compare と /api/chat の統合テスト。

LLM は MockLLMClient で差し替え、外部 API を叩かない。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

pytestmark = pytest.mark.asyncio


def _scenario_payload(name: str, *, primary: str = "6000000", spouse: str = "3000000") -> dict:
    return {
        "name": name,
        "description": f"シナリオ {name}",
        "primary_salary": primary,
        "spouse_salary": spouse,
        "base_annual_expense": "4200000",
        "initial_net_worth": "5000000",
        "start_year": 2026,
        "horizon_years": 30,
        "salary_growth_rate": "0.01",
        "inflation_rate": "0.01",
        "investment_return_rate": "0.02",
    }


# --- /api/scenarios/compare ---


async def test_compare_baseline_vs_birth_event(client):
    # ベースシナリオ
    r = await client.post("/api/scenarios", json=_scenario_payload("Baseline"))
    base_id = r.json()["id"]

    # 比較: 出産イベント入り
    r = await client.post("/api/scenarios", json=_scenario_payload("WithChild"))
    child_id = r.json()["id"]
    await client.post(
        f"/api/scenarios/{child_id}/events",
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

    r = await client.post(
        "/api/scenarios/compare",
        json={"base_scenario_id": base_id, "compare_scenario_ids": [child_id]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["base"]["scenario_id"] == base_id
    assert len(body["compares"]) == 1
    assert len(body["diffs"]) == 1
    # 出産ありは純資産が減る
    assert Decimal(body["diffs"][0]["net_worth_diff"]) < Decimal("0")


async def test_compare_requires_compare_scenarios(client):
    r = await client.post("/api/scenarios", json=_scenario_payload("Baseline"))
    base_id = r.json()["id"]
    r = await client.post(
        "/api/scenarios/compare",
        json={"base_scenario_id": base_id, "compare_scenario_ids": []},
    )
    assert r.status_code == 422


async def test_compare_base_not_found(client):
    r = await client.post(
        "/api/scenarios/compare",
        json={"base_scenario_id": 9999, "compare_scenario_ids": [1]},
    )
    assert r.status_code == 404


async def test_compare_multiple_alternatives(client):
    r = await client.post("/api/scenarios", json=_scenario_payload("Base"))
    base_id = r.json()["id"]
    ids = [base_id]
    for name in ["Alt1", "Alt2"]:
        r = await client.post("/api/scenarios", json=_scenario_payload(name))
        ids.append(r.json()["id"])
    r = await client.post(
        "/api/scenarios/compare",
        json={"base_scenario_id": ids[0], "compare_scenario_ids": ids[1:]},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["compares"]) == 2
    assert len(body["diffs"]) == 2


# --- /api/chat ---


async def test_chat_summarize_single_scenario(client):
    """LLM_MOCK_MODE で単一シナリオの要約ルート。"""
    r = await client.post("/api/scenarios", json=_scenario_payload("Baseline"))
    sid = r.json()["id"]
    r = await client.post(
        "/api/chat", json={"scenario_ids": [sid], "question": "この前提で老後は大丈夫？"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "summarize"
    assert body["scenario_ids"] == [sid]
    assert body["narrative"]
    # Mock client は「モック」という語を返す
    assert "モック" in body["narrative"]


async def test_chat_compare_two_scenarios(client):
    r = await client.post("/api/scenarios", json=_scenario_payload("Base"))
    base_id = r.json()["id"]
    r = await client.post("/api/scenarios", json=_scenario_payload("Alt"))
    alt_id = r.json()["id"]
    r = await client.post(
        "/api/chat",
        json={"scenario_ids": [base_id, alt_id], "question": "どちらが有利？"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "compare"
    assert body["scenario_ids"] == [base_id, alt_id]


async def test_chat_rejects_empty_scenarios(client):
    r = await client.post("/api/chat", json={"scenario_ids": [], "question": "?"})
    assert r.status_code == 422


async def test_chat_scenario_not_found(client):
    r = await client.post("/api/chat", json={"scenario_ids": [9999]})
    assert r.status_code == 404


async def test_chat_max_5_scenarios(client):
    """scenario_ids は最大 5 件まで。"""
    r = await client.post(
        "/api/chat", json={"scenario_ids": [1, 2, 3, 4, 5, 6]}
    )
    assert r.status_code == 422
