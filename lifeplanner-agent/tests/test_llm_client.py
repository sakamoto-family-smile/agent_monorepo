"""LLM クライアント (MockLLMClient / build_default_client) のテスト。"""

from __future__ import annotations

import pytest
from services.llm_client import (
    AnthropicLLMClient,
    MockLLMClient,
    get_llm_client,
    set_llm_client,
)


@pytest.mark.asyncio
async def test_mock_client_returns_fixed_reply():
    client = MockLLMClient(fixed_reply="hello")
    out = await client.complete(system="sys", user="u")
    assert out == "hello"


@pytest.mark.asyncio
async def test_mock_client_echoes_user_preview():
    client = MockLLMClient()
    out = await client.complete(system="sys", user="1行目\n2行目")
    assert "1行目" in out
    assert "モック" in out


def test_build_default_client_uses_mock_when_flag_set(monkeypatch):
    monkeypatch.setenv("LLM_MOCK_MODE", "true")
    import importlib

    import config as config_mod

    importlib.reload(config_mod)
    import services.llm_client as llm_mod

    importlib.reload(llm_mod)
    assert isinstance(llm_mod.build_default_client(), llm_mod.MockLLMClient)


def test_build_default_client_uses_mock_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("LLM_MOCK_MODE", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import importlib

    import config as config_mod

    importlib.reload(config_mod)
    import services.llm_client as llm_mod

    importlib.reload(llm_mod)
    assert isinstance(llm_mod.build_default_client(), llm_mod.MockLLMClient)


def test_set_llm_client_overrides_default():
    custom = MockLLMClient(fixed_reply="custom")
    set_llm_client(custom)
    assert get_llm_client() is custom
    set_llm_client(None)  # reset


def test_anthropic_client_constructs_without_call():
    """API キーがあれば AnthropicLLMClient がインスタンス化できる (HTTP 呼出しはしない)。"""
    c = AnthropicLLMClient(api_key="sk-test", model="claude-sonnet-4-6", max_tokens=100)
    assert c is not None
