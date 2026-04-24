"""LLM クライアント (MockLLMClient / build_default_client) のテスト。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

# `_system_payload` は llm-client パッケージに移行。shim は public 名 `system_payload`
# を経由せず、テストでは直接パッケージから取得する (shim の詳細スキーマテストは
# llm-client/tests/test_client.py に移設済)。
from llm_client import system_payload as _system_payload
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


def test_build_default_client_vertex_without_project_falls_back_to_mock(monkeypatch):
    """LLM_PROVIDER=vertex かつ GOOGLE_CLOUD_PROJECT 未設定 → MockLLMClient。"""
    monkeypatch.delenv("LLM_MOCK_MODE", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "vertex")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    import importlib

    import config as config_mod

    importlib.reload(config_mod)
    import services.llm_client as llm_mod

    importlib.reload(llm_mod)
    assert isinstance(llm_mod.build_default_client(), llm_mod.MockLLMClient)


def test_build_default_client_unknown_provider_treated_as_anthropic(monkeypatch):
    """未知のプロバイダ名は anthropic 扱い。APIキー未設定で Mock にフォールバック。"""
    monkeypatch.delenv("LLM_MOCK_MODE", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "bogus")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import importlib

    import config as config_mod

    importlib.reload(config_mod)
    import services.llm_client as llm_mod

    importlib.reload(llm_mod)
    assert isinstance(llm_mod.build_default_client(), llm_mod.MockLLMClient)


# ---------------------------------------------------------------------------
# Prompt caching
# ---------------------------------------------------------------------------


def test_system_payload_without_cache_returns_plain_string():
    assert _system_payload("hello", cache=False) == "hello"


def test_system_payload_with_cache_returns_blocks_with_cache_control():
    out = _system_payload("hello", cache=True)
    assert isinstance(out, list)
    assert len(out) == 1
    block = out[0]
    assert block["type"] == "text"
    assert block["text"] == "hello"
    assert block["cache_control"] == {"type": "ephemeral"}


@pytest.mark.asyncio
async def test_mock_client_complete_accepts_cache_system_flag():
    """MockLLMClient の complete は cache_system を受けても挙動変わらず。"""
    client = MockLLMClient(fixed_reply="ok")
    assert await client.complete(system="s", user="u") == "ok"
    assert await client.complete(system="s", user="u", cache_system=True) == "ok"


@pytest.mark.asyncio
async def test_mock_client_complete_messages_uses_last_user_message():
    client = MockLLMClient()
    out = await client.complete_messages(
        system="s",
        messages=[
            {"role": "user", "content": "最初の質問"},
            {"role": "assistant", "content": "回答1"},
            {"role": "user", "content": "追加の質問"},
        ],
    )
    assert "追加の質問" in out
    assert "履歴 3 件" in out


@pytest.mark.asyncio
async def test_mock_client_complete_messages_respects_fixed_reply():
    client = MockLLMClient(fixed_reply="固定")
    out = await client.complete_messages(
        system="s",
        messages=[{"role": "user", "content": "q"}],
        cache_system=True,
    )
    assert out == "固定"


@pytest.mark.asyncio
async def test_anthropic_client_complete_passes_cache_control_when_requested():
    """AnthropicLLMClient.complete(cache_system=True) で system が cache_control 付きブロック化される。"""
    c = AnthropicLLMClient(api_key="sk-test", model="claude-sonnet-4-6", max_tokens=100)

    # resp.content を TextBlock 風にスタブ
    class _StubBlock:
        text = "reply"

    class _StubResp:
        content = [_StubBlock()]
        usage = None
        stop_reason = "end_turn"

    mock_create = AsyncMock(return_value=_StubResp())
    c._client.messages.create = mock_create  # type: ignore[assignment]

    out = await c.complete(system="SYS", user="USER", cache_system=True)
    assert out == "reply"

    mock_create.assert_awaited_once()
    kwargs = mock_create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-4-6"
    assert kwargs["max_tokens"] == 100
    assert kwargs["system"] == [
        {
            "type": "text",
            "text": "SYS",
            "cache_control": {"type": "ephemeral"},
        }
    ]
    assert kwargs["messages"] == [{"role": "user", "content": "USER"}]


@pytest.mark.asyncio
async def test_anthropic_client_complete_defaults_to_plain_system_string():
    """cache_system を省略すると system は既存通り str のままで渡る (後方互換)。"""
    c = AnthropicLLMClient(api_key="sk-test", model="claude-sonnet-4-6", max_tokens=100)

    class _StubBlock:
        text = "reply"

    class _StubResp:
        content = [_StubBlock()]
        usage = None
        stop_reason = None

    mock_create = AsyncMock(return_value=_StubResp())
    c._client.messages.create = mock_create  # type: ignore[assignment]

    await c.complete(system="SYS", user="USER")

    kwargs = mock_create.call_args.kwargs
    assert kwargs["system"] == "SYS"


@pytest.mark.asyncio
async def test_anthropic_client_complete_messages_forwards_messages_and_cache():
    """complete_messages が会話履歴をそのまま渡し、cache_system で system をブロック化する。"""
    c = AnthropicLLMClient(api_key="sk-test", model="claude-sonnet-4-6", max_tokens=100)

    class _StubBlock:
        text = "reply"

    class _StubResp:
        content = [_StubBlock()]
        usage = None
        stop_reason = None

    mock_create = AsyncMock(return_value=_StubResp())
    c._client.messages.create = mock_create  # type: ignore[assignment]

    history = [
        {"role": "user", "content": "過去1"},
        {"role": "assistant", "content": "応答1"},
        {"role": "user", "content": "今回"},
    ]
    out = await c.complete_messages(system="SYS", messages=history, cache_system=True)
    assert out == "reply"

    kwargs = mock_create.call_args.kwargs
    assert kwargs["messages"] == history
    assert isinstance(kwargs["system"], list)
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
