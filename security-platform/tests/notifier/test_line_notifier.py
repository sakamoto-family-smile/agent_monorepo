"""LINE Messaging API notifier のテスト。

- 未設定時は False (channel secret / token 欠落 or user_ids 欠落)
- 複数 userId への push 実行
- 個別 push 失敗があっても他の送信は続行、少なくとも 1 件成功なら True
- すべて失敗なら False
- 旧 LINE_NOTIFY_TOKEN が設定されていれば deprecation 警告
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.config import settings


@pytest.fixture
def line_config(monkeypatch):
    """LINE Messaging API 設定を有効化する。"""
    monkeypatch.setattr(settings, "line_channel_secret", "test-secret")
    monkeypatch.setattr(settings, "line_channel_access_token", "test-token")
    monkeypatch.setattr(settings, "line_user_ids", "Uaaa,Ubbb")
    monkeypatch.setattr(settings, "line_notify_token", "")


@pytest.fixture
def mock_sdk(monkeypatch):
    """line-bot-sdk v3 の AsyncApiClient / AsyncMessagingApi をモック。"""
    api_client = AsyncMock()
    api_client.close = AsyncMock()

    messaging = AsyncMock()
    messaging.push_message = AsyncMock(return_value=None)

    def _fake_configuration(access_token):
        return object()

    def _fake_async_api_client(config):
        return api_client

    def _fake_async_messaging_api(client):
        return messaging

    # linebot.v3.messaging からの import を差し替え
    import linebot.v3.messaging as lm

    monkeypatch.setattr(lm, "Configuration", _fake_configuration)
    monkeypatch.setattr(lm, "AsyncApiClient", _fake_async_api_client)
    monkeypatch.setattr(lm, "AsyncMessagingApi", _fake_async_messaging_api)

    # PushMessageRequest / TextMessage は実体利用 (ただの dataclass-like)
    return {"api_client": api_client, "messaging": messaging}


# ---------------------------------------------------------------------------
# 未設定時の挙動
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_false_when_channel_missing(monkeypatch):
    monkeypatch.setattr(settings, "line_channel_secret", "")
    monkeypatch.setattr(settings, "line_channel_access_token", "")
    monkeypatch.setattr(settings, "line_user_ids", "Uaaa")

    from src.notifier.line import send_message

    assert await send_message("hi") is False


@pytest.mark.asyncio
async def test_returns_false_when_user_ids_missing(monkeypatch):
    monkeypatch.setattr(settings, "line_channel_secret", "s")
    monkeypatch.setattr(settings, "line_channel_access_token", "t")
    monkeypatch.setattr(settings, "line_user_ids", "")

    from src.notifier.line import send_message

    assert await send_message("hi") is False


@pytest.mark.asyncio
async def test_returns_false_when_only_whitespace_user_ids(monkeypatch):
    monkeypatch.setattr(settings, "line_channel_secret", "s")
    monkeypatch.setattr(settings, "line_channel_access_token", "t")
    monkeypatch.setattr(settings, "line_user_ids", " , , ")

    from src.notifier.line import send_message

    assert await send_message("hi") is False


# ---------------------------------------------------------------------------
# 正常系: push_message が user 数分呼ばれる
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_to_all_recipients(line_config, mock_sdk):
    from src.notifier.line import send_message

    ok = await send_message("security digest body")
    assert ok is True
    assert mock_sdk["messaging"].push_message.await_count == 2

    # 各呼出しの引数検証
    calls = mock_sdk["messaging"].push_message.call_args_list
    recipients = [c.args[0].to for c in calls]
    assert set(recipients) == {"Uaaa", "Ubbb"}


@pytest.mark.asyncio
async def test_push_truncates_long_messages(line_config, mock_sdk):
    from src.notifier.line import send_message

    long_text = "a" * 10_000
    ok = await send_message(long_text)
    assert ok is True

    # 送られたテキストが 4900 以下に収まる
    first_call = mock_sdk["messaging"].push_message.call_args_list[0]
    msg_text = first_call.args[0].messages[0].text
    assert len(msg_text) <= 4900
    assert msg_text.endswith("...(以下省略)")


# ---------------------------------------------------------------------------
# 失敗系: 一部失敗でも他は続行、api_client.close は必ず呼ばれる
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_partial_failure_returns_true_if_any_success(line_config, mock_sdk):
    """1 人目が失敗、2 人目が成功 → True 返却。"""
    responses = [Exception("boom"), None]

    async def side_effect(*args, **kwargs):
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return None

    mock_sdk["messaging"].push_message = AsyncMock(side_effect=side_effect)

    from src.notifier.line import send_message

    ok = await send_message("hi")
    assert ok is True
    assert mock_sdk["api_client"].close.await_count == 1


@pytest.mark.asyncio
async def test_all_failures_return_false(line_config, mock_sdk):
    mock_sdk["messaging"].push_message = AsyncMock(side_effect=Exception("down"))

    from src.notifier.line import send_message

    ok = await send_message("hi")
    assert ok is False
    assert mock_sdk["api_client"].close.await_count == 1


# ---------------------------------------------------------------------------
# 旧 LINE_NOTIFY_TOKEN 互換 (deprecation 警告)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_notify_token_triggers_deprecation_warning(
    line_config, mock_sdk, caplog, monkeypatch
):
    monkeypatch.setattr(settings, "line_notify_token", "legacy-token-xxx")

    from src.notifier.line import send_message

    with caplog.at_level("WARNING"):
        await send_message("hi")

    assert any(
        "LINE_NOTIFY_TOKEN is set" in rec.message and "terminated" in rec.message
        for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_no_deprecation_warning_when_legacy_token_absent(
    line_config, mock_sdk, caplog
):
    from src.notifier.line import send_message

    with caplog.at_level("WARNING"):
        await send_message("hi")

    assert not any(
        "LINE_NOTIFY_TOKEN" in rec.message for rec in caplog.records
    )
