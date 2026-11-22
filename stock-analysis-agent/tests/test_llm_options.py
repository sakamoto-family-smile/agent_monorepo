"""gateway 経由の接続設定 (PROPOSAL-0014)。"""

from __future__ import annotations

import json

import pytest
from agents import llm_options

from config import Settings

TRACE = "0123456789abcdef0123456789abcdef"


def _settings(**overrides) -> Settings:
    s = Settings()
    s.llm_model = "claude-opus-5-5"
    s.llm_gateway_url = ""
    s.llm_gateway_key = ""
    s.llm_gateway_model = "stock-analysis"
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def test_direct_mode_keeps_previous_env(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth")
    env = llm_options.claude_env(_settings(), TRACE)
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth"
    assert "ANTHROPIC_BASE_URL" not in env
    assert "ANTHROPIC_CUSTOM_HEADERS" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert llm_options.claude_settings(_settings()) is None
    assert llm_options.model_label(_settings()) == "claude-opus-5-5"


def test_gateway_mode_sends_key_and_trace_headers(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth")
    s = _settings(llm_gateway_url="http://litellm:4000", llm_gateway_key="sk-virtual")
    env = llm_options.claude_env(s, TRACE)
    assert env["ANTHROPIC_BASE_URL"] == "http://litellm:4000"
    headers = env["ANTHROPIC_CUSTOM_HEADERS"].split("\n")
    assert headers == ["x-litellm-api-key: Bearer sk-virtual", f"x-litellm-trace-id: {TRACE}"]
    # 定額プランの間は OAuth トークンを gateway がそのまま Anthropic に渡す
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth"
    assert "ANTHROPIC_AUTH_TOKEN" not in env


def test_gateway_mode_maps_model_to_alias():
    s = _settings(llm_gateway_url="http://litellm:4000", llm_gateway_key="k")
    assert json.loads(llm_options.claude_settings(s)) == {
        "modelOverrides": {"claude-opus-5-5": "stock-analysis"}
    }
    assert llm_options.model_label(s) == "stock-analysis"


def test_gateway_without_key_fails_fast():
    with pytest.raises(RuntimeError, match="LLM_GATEWAY_KEY"):
        llm_options.claude_env(_settings(llm_gateway_url="http://litellm:4000"), TRACE)


def test_trace_id_is_32_hex():
    t = llm_options.new_trace_id()
    assert len(t) == 32 and int(t, 16) >= 0
    assert t != llm_options.new_trace_id()


def test_disallows_shell_and_file_writes():
    for tool in ("Bash", "Write", "Edit"):
        assert tool in llm_options.DISALLOWED_TOOLS
    assert "Read" not in llm_options.DISALLOWED_TOOLS
