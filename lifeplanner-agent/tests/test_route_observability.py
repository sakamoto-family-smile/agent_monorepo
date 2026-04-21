"""ルート計装の統合テスト。

各ルートを HTTP 経由で叩き、AnalyticsLogger に流れる業務イベントを検証する。
LLM は MockLLMClient で差し替え、外部 API は叩かない。
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest_asyncio


@dataclass
class _MemorySink:
    written: list[str] = field(default_factory=list)

    async def write_batch(self, lines: list[str]) -> None:
        self.written.extend(lines)


@pytest_asyncio.fixture
async def client_with_sink(tmp_path: Path, monkeypatch):
    """conftest の `client` と同等だが、AnalyticsLogger の sink を MemorySink に置換。"""
    db_url = f"sqlite+aiosqlite:///{tmp_path}/api.db"
    monkeypatch.setenv("DB_URL", db_url)
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MF_CSV_DIR", str(tmp_path / "mf_csv"))
    monkeypatch.setenv("DEV_HOUSEHOLD_ID", "test-household")
    monkeypatch.setenv("LLM_MOCK_MODE", "true")
    monkeypatch.setenv("ANALYTICS_ENABLED", "true")
    monkeypatch.setenv("ANALYTICS_DATA_DIR", str(tmp_path / "analytics"))
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")

    import config

    importlib.reload(config)
    from services import database as db_mod

    importlib.reload(db_mod)
    from services import llm_client as llm_mod

    importlib.reload(llm_mod)
    llm_mod.set_llm_client(None)

    import instrumentation

    instrumentation.reset_for_tests()

    import main

    importlib.reload(main)

    from analytics_platform.observability.analytics_logger import AnalyticsLogger
    from httpx import ASGITransport, AsyncClient

    sink = _MemorySink()
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as c:
        async with main.app.router.lifespan_context(main.app):
            # lifespan の setup_observability() が走った後で sink を差し替える
            from instrumentation import setup as setup_mod

            replacement = AnalyticsLogger(
                service_name=config.settings.analytics_service_name,
                service_version=config.settings.service_version,
                environment=config.settings.app_env,
                sink=sink,
            )
            setup_mod._analytics_logger = replacement
            yield c, sink, replacement

    instrumentation.reset_for_tests()


def _events(sink: _MemorySink) -> list[dict]:
    return [json.loads(line) for line in sink.written]


def _by_action(sink: _MemorySink) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for ev in _events(sink):
        if ev.get("event_type") == "business_event":
            grouped.setdefault(ev["action"], []).append(ev)
    return grouped


def _scenario_payload() -> dict:
    return {
        "name": "BaseScenario",
        "description": "obs test",
        "primary_salary": "6000000",
        "spouse_salary": "3000000",
        "base_annual_expense": "4200000",
        "initial_net_worth": "5000000",
        "start_year": 2026,
        "horizon_years": 10,
        "salary_growth_rate": "0.01",
        "inflation_rate": "0.01",
        "investment_return_rate": "0.02",
    }


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


async def test_scenario_create_emits_business_event(client_with_sink):
    client, sink, al = client_with_sink

    r = await client.post("/api/scenarios", json=_scenario_payload())
    assert r.status_code == 201
    await al.flush()

    actions = _by_action(sink)
    assert "scenario_created" in actions
    ev = actions["scenario_created"][0]
    assert ev["resource_type"] == "scenario"
    assert ev["user_id"] == "test-household"


async def test_scenario_simulate_emits_business_event(client_with_sink):
    client, sink, al = client_with_sink

    r = await client.post("/api/scenarios", json=_scenario_payload())
    sid = r.json()["id"]
    r = await client.post(f"/api/scenarios/{sid}/simulate")
    assert r.status_code == 200
    await al.flush()

    actions = _by_action(sink)
    assert "scenario_simulated" in actions
    ev = actions["scenario_simulated"][0]
    assert ev["attributes"]["horizon_years"] == 10


async def test_chat_emits_business_event(client_with_sink):
    client, sink, al = client_with_sink

    r = await client.post("/api/scenarios", json=_scenario_payload())
    sid = r.json()["id"]
    await client.post(f"/api/scenarios/{sid}/simulate")  # 必要

    r = await client.post(
        "/api/chat",
        json={"scenario_ids": [sid], "question": "現状はどう?"},
    )
    assert r.status_code == 200
    await al.flush()

    actions = _by_action(sink)
    assert "chat_completed" in actions
    ev = actions["chat_completed"][0]
    assert ev["attributes"]["had_question"] is True
    assert ev["attributes"]["scenario_count"] == 1


async def test_chat_404_emits_error_event(client_with_sink):
    client, sink, al = client_with_sink

    r = await client.post("/api/chat", json={"scenario_ids": [9999], "question": None})
    assert r.status_code == 404
    await al.flush()

    err = [ev for ev in _events(sink) if ev.get("event_type") == "error_event"]
    assert err
    assert err[0]["error_category"] == "validation"


async def test_upload_csv_emits_business_event(client_with_sink, tmp_path: Path):
    client, sink, al = client_with_sink

    # 最小限の有効な MF CSV (Shift-JIS、列名は full-width 括弧)
    csv_text = (
        "計算対象,日付,内容,金額（円）,保有金融機関,大項目,中項目,メモ,振替,ID\n"
        "1,2026/04/15,test,-1000,bank,食費,食料品,,0,id_1\n"
    )
    raw = csv_text.encode("shift_jis")

    files = {"file": ("test.csv", raw, "text/csv")}
    r = await client.post("/api/upload", files=files)
    assert r.status_code == 200, r.text
    await al.flush()

    actions = _by_action(sink)
    assert "csv_imported" in actions
    ev = actions["csv_imported"][0]
    assert ev["attributes"]["imported"] >= 1
    assert ev["resource_id"] == "test.csv"
