"""FastAPI integration tests for the MCP Gateway (server.py)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_gateway_mode(gateway_client):
    """Ensure the gateway mode is reset to passive after each test."""
    yield
    from src.proxy import server as server_module
    server_module._gateway_mode = "passive"


def test_health_endpoint(gateway_client):
    resp = gateway_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "mcp-gateway"
    assert "mode" in data


def test_get_mode(gateway_client):
    resp = gateway_client.get("/mode")
    assert resp.status_code == 200
    data = resp.json()
    assert "mode" in data
    assert data["mode"] in ("passive", "active")


def test_set_mode_active(gateway_client):
    resp = gateway_client.post("/mode", json={"mode": "active"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "active"
    assert data["previous"] == "passive"

    # Verify mode actually changed
    mode_resp = gateway_client.get("/mode")
    assert mode_resp.json()["mode"] == "active"


def test_set_mode_invalid(gateway_client):
    resp = gateway_client.post("/mode", json={"mode": "invalid_mode"})
    assert resp.status_code == 400


def test_list_tools_empty(gateway_client):
    resp = gateway_client.get("/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert "tools" in data
    assert isinstance(data["tools"], list)


def test_audit_log_empty(gateway_client):
    resp = gateway_client.get("/audit-log")
    assert resp.status_code == 200
    data = resp.json()
    assert "entries" in data
    assert isinstance(data["entries"], list)


def test_stats_endpoint(gateway_client):
    resp = gateway_client.get("/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "mode" in data
    assert "rate_limiter" in data
    assert "target_url" in data


def test_clean_tool_call_passive_mode(gateway_client):
    """In passive mode, a clean tool call should return 200 with gateway passthrough."""
    resp = gateway_client.post(
        "/proxy/search",
        json={"parameters": {"query": "python tutorials"}},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Downstream is unavailable → passthrough response
    assert data.get("status") == "gateway_passthrough"


def test_injection_in_passive_mode_not_blocked(gateway_client):
    """In passive mode, an injection payload is logged but not blocked (returns 200)."""
    from src.proxy import server as server_module
    server_module._gateway_mode = "passive"

    resp = gateway_client.post(
        "/proxy/exec",
        json={"parameters": {"cmd": "; rm -rf /"}},
    )
    # Passive mode: logged but not blocked
    assert resp.status_code == 200


def test_injection_in_active_mode_blocked(gateway_client):
    """In active mode, an injection payload should return 400."""
    from src.proxy import server as server_module
    server_module._gateway_mode = "active"

    resp = gateway_client.post(
        "/proxy/exec",
        json={"parameters": {"cmd": "; rm -rf /"}},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert "INJECTION" in data.get("detail", "")


def test_dlp_in_active_mode_blocked(gateway_client):
    """In active mode, a request with an API key in params should return 400."""
    from src.proxy import server as server_module
    server_module._gateway_mode = "active"

    resp = gateway_client.post(
        "/proxy/config",
        json={"parameters": {"config": "api_key: sk-verylongapikey1234567890abcdefghij"}},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert "DLP_OUTBOUND" in data.get("detail", "")
