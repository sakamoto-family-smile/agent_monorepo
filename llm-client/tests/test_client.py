"""llm-client 本体テスト。

lifeplanner-agent の test_llm_client.py から移植。build_default_client /
settings 依存部分は落とし、代わりに on_call コールバック挙動を検証する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from llm_client import (
    AnthropicLLMClient,
    MockLLMClient,
    VertexAnthropicLLMClient,
    system_payload,
)

# ---------------------------------------------------------------------------
# system_payload
# ---------------------------------------------------------------------------


def test_system_payload_without_cache_returns_plain_string():
    assert system_payload("hello", cache=False) == "hello"


def test_system_payload_with_cache_returns_blocks_with_cache_control():
    out = system_payload("hello", cache=True)
    assert isinstance(out, list)
    assert len(out) == 1
    assert out[0] == {
        "type": "text",
        "text": "hello",
        "cache_control": {"type": "ephemeral"},
    }


# ---------------------------------------------------------------------------
# MockLLMClient
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_returns_fixed_reply():
    client = MockLLMClient(fixed_reply="hello")
    assert await client.complete(system="s", user="u") == "hello"


@pytest.mark.asyncio
async def test_mock_echoes_user_preview():
    client = MockLLMClient()
    out = await client.complete(system="s", user="1行目\n2行目")
    assert "1行目" in out
    assert "モック" in out


@pytest.mark.asyncio
async def test_mock_accepts_cache_system_flag():
    client = MockLLMClient(fixed_reply="ok")
    assert await client.complete(system="s", user="u", cache_system=True) == "ok"


@pytest.mark.asyncio
async def test_mock_complete_messages_uses_last_user_message():
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
async def test_mock_complete_messages_fixed_reply():
    client = MockLLMClient(fixed_reply="固定")
    out = await client.complete_messages(
        system="s",
        messages=[{"role": "user", "content": "q"}],
        cache_system=True,
    )
    assert out == "固定"


# ---------------------------------------------------------------------------
# Construction (no network call)
# ---------------------------------------------------------------------------


def test_anthropic_client_constructs():
    c = AnthropicLLMClient(api_key="sk-test", model="claude-sonnet-4-6", max_tokens=100)
    assert c is not None


def test_vertex_client_constructs(monkeypatch):
    """AsyncAnthropicVertex は credential lookup するので google 認証無しでも
    コンストラクタは通すよう、環境変数を suppress して試す。"""
    # Credential lookup を避けるため FakeADC 的な env を差し込む
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "dummy")
    # 実際の API call は行わないため construct だけ通ればよい
    try:
        c = VertexAnthropicLLMClient(
            project_id="p", region="us-east5", model="claude-sonnet-4-6@20260101", max_tokens=100
        )
        assert c is not None
    except Exception:
        # credential 解決に失敗するケースもテスト環境次第で起こり得る。
        # その場合は skip 相当で許容 (クライアントコンストラクタは anthropic SDK 依存)
        pytest.skip("Vertex client requires working ADC; skipping if not available")


# ---------------------------------------------------------------------------
# Anthropic wire format
# ---------------------------------------------------------------------------


class _StubTextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _StubResp:
    def __init__(self, text: str = "reply", usage=None, stop_reason=None) -> None:
        self.content = [_StubTextBlock(text)]
        self.usage = usage
        self.stop_reason = stop_reason


@pytest.mark.asyncio
async def test_complete_cache_system_wraps_system_with_cache_control():
    c = AnthropicLLMClient(api_key="sk-test", model="m", max_tokens=100)
    mock_create = AsyncMock(return_value=_StubResp())
    c._client.messages.create = mock_create  # type: ignore[assignment]

    out = await c.complete(system="SYS", user="USER", cache_system=True)
    assert out == "reply"

    kwargs = mock_create.call_args.kwargs
    assert kwargs["model"] == "m"
    assert kwargs["max_tokens"] == 100
    assert kwargs["system"] == [
        {"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}
    ]
    assert kwargs["messages"] == [{"role": "user", "content": "USER"}]


@pytest.mark.asyncio
async def test_complete_without_cache_system_passes_plain_string():
    c = AnthropicLLMClient(api_key="sk-test", model="m", max_tokens=100)
    mock_create = AsyncMock(return_value=_StubResp())
    c._client.messages.create = mock_create  # type: ignore[assignment]

    await c.complete(system="SYS", user="USER")

    kwargs = mock_create.call_args.kwargs
    assert kwargs["system"] == "SYS"


@pytest.mark.asyncio
async def test_complete_messages_forwards_history_and_cache():
    c = AnthropicLLMClient(api_key="sk-test", model="m", max_tokens=100)
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


# ---------------------------------------------------------------------------
# on_call callback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_call_invoked_on_success():
    captured = []

    def on_call(event):
        captured.append(event)

    c = AnthropicLLMClient(api_key="sk-test", model="m", max_tokens=100, on_call=on_call)
    c._client.messages.create = AsyncMock(return_value=_StubResp(text="ok"))  # type: ignore[assignment]

    await c.complete(system="s", user="u")

    assert len(captured) == 1
    ev = captured[0]
    assert ev["provider"] == "anthropic"
    assert ev["model"] == "m"
    assert ev["error"] is None
    assert ev["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_on_call_invoked_on_error_and_exception_reraised():
    captured = []

    def on_call(event):
        captured.append(event)

    c = AnthropicLLMClient(api_key="sk-test", model="m", max_tokens=100, on_call=on_call)

    class Boom(Exception): ...

    c._client.messages.create = AsyncMock(side_effect=Boom("kaboom"))  # type: ignore[assignment]

    with pytest.raises(Boom):
        await c.complete(system="s", user="u")

    assert len(captured) == 1
    ev = captured[0]
    assert ev["resp"] is None
    assert isinstance(ev["error"], Boom)


@pytest.mark.asyncio
async def test_on_call_exception_is_swallowed_not_to_break_caller():
    def on_call(event):
        raise RuntimeError("callback explodes")

    c = AnthropicLLMClient(api_key="sk-test", model="m", max_tokens=100, on_call=on_call)
    c._client.messages.create = AsyncMock(return_value=_StubResp(text="ok"))  # type: ignore[assignment]

    # コールバックがこけても本処理は戻り値を返せる
    out = await c.complete(system="s", user="u")
    assert out == "ok"


# ---------------------------------------------------------------------------
# analytics helper (optional module)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_make_analytics_on_call_emits_to_logger():
    """`analytics.make_analytics_on_call` が logger.emit を呼ぶ。"""
    from llm_client.analytics import make_analytics_on_call

    emitted = []

    class StubLogger:
        def emit(
            self, *, event_type, event_version, severity, fields,
            user_id=None, session_id=None,
        ):
            emitted.append(
                {
                    "event_type": event_type,
                    "severity": severity,
                    "fields": dict(fields),
                }
            )
            return "id1"

    on_call = make_analytics_on_call(lambda: StubLogger())

    class _Usage:
        input_tokens = 10
        output_tokens = 20
        cache_read_input_tokens = 5
        cache_creation_input_tokens = 2

    class _Resp:
        content = [_StubTextBlock("ok")]
        usage = _Usage()
        stop_reason = "end_turn"

    c = AnthropicLLMClient(api_key="sk-test", model="m", max_tokens=100, on_call=on_call)
    c._client.messages.create = AsyncMock(return_value=_Resp())  # type: ignore[assignment]

    await c.complete(system="s", user="u")

    assert len(emitted) == 1
    rec = emitted[0]
    assert rec["event_type"] == "llm_call"
    assert rec["severity"] == "INFO"
    fields = rec["fields"]
    assert fields["llm_provider"] == "anthropic"
    assert fields["llm_model"] == "m"
    assert fields["input_tokens"] == 10
    assert fields["output_tokens"] == 20
    assert fields["cache_read_tokens"] == 5
    assert fields["cache_creation_tokens"] == 2
    assert fields["stop_reason"] == "end_turn"


@pytest.mark.asyncio
async def test_make_analytics_on_call_with_null_logger_is_noop():
    from llm_client.analytics import make_analytics_on_call

    # logger_factory が None を返す: setup 前を想定
    on_call = make_analytics_on_call(lambda: None)

    c = AnthropicLLMClient(api_key="sk-test", model="m", max_tokens=100, on_call=on_call)
    c._client.messages.create = AsyncMock(return_value=_StubResp())  # type: ignore[assignment]

    # エラーにならないこと (callback の safe_emit で吸収)
    out = await c.complete(system="s", user="u")
    assert out == "reply"
