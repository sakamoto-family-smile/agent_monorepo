"""LINE webhook route のテスト (Phase 1: echo reply)。

実 LINE SDK の `WebhookParser` を使い、 LINE 公式仕様の JSON + 正規署名で
end-to-end に動作確認する。 `reply_text` は `LineBotClient` をモンキーパッチで
capture する。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app import line_client as line_client_module
from app.line_client import LineBotClient, reset_line_bot_client
from app.main import app

_SECRET = "test-channel-secret"
_TOKEN = "test-channel-access-token"


def _sign(body: bytes, secret: str = _SECRET) -> str:
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(mac).decode("utf-8")


def _make_text_event(*, text: str, reply_token: str = "reply-1") -> dict:
    """LINE webhook の本物の JSON 形式を最小限で再現。"""
    return {
        "type": "message",
        "replyToken": reply_token,
        "source": {"type": "user", "userId": "U_test"},
        "timestamp": 1700000000000,
        "mode": "active",
        "webhookEventId": "evt-1",
        "deliveryContext": {"isRedelivery": False},
        "message": {
            "type": "text",
            "id": "msg-1",
            "quoteToken": "qt-1",
            "text": text,
        },
    }


class _CapturingClient(LineBotClient):
    """`reply_text` をモックして送信内容を capture する。"""

    def __init__(self, *, channel_secret: str, channel_access_token: str) -> None:
        super().__init__(channel_secret=channel_secret, channel_access_token=channel_access_token)
        self.replies: list[tuple[str, list[str]]] = []

    def reply_text(self, reply_token: str, messages: list[str]) -> None:  # type: ignore[override]
        self.replies.append((reply_token, messages))


@pytest.fixture
def line_client_capturing(monkeypatch: pytest.MonkeyPatch) -> _CapturingClient:
    """settings に test 値を流し、 LineBotClient を CapturingClient に差し替える。"""
    monkeypatch.setattr(line_client_module.settings, "line_channel_secret", _SECRET, raising=False)
    monkeypatch.setattr(
        line_client_module.settings, "line_channel_access_token", _TOKEN, raising=False
    )
    reset_line_bot_client()
    client = _CapturingClient(channel_secret=_SECRET, channel_access_token=_TOKEN)
    monkeypatch.setattr(line_client_module, "_client_singleton", client, raising=False)
    yield client
    reset_line_bot_client()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestWebhook:
    def test_returns_503_when_line_not_configured(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            line_client_module.settings, "line_channel_secret", "", raising=False
        )
        monkeypatch.setattr(
            line_client_module.settings, "line_channel_access_token", "", raising=False
        )
        reset_line_bot_client()

        body = json.dumps({"events": []}).encode("utf-8")
        resp = client.post(
            "/webhook",
            content=body,
            headers={
                "X-Line-Signature": _sign(body),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 503

    def test_returns_401_on_invalid_signature(
        self, client: TestClient, line_client_capturing: _CapturingClient
    ) -> None:
        body = json.dumps({"events": []}).encode("utf-8")
        resp = client.post(
            "/webhook",
            content=body,
            headers={
                "X-Line-Signature": "obviously-wrong",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401
        assert line_client_capturing.replies == []

    def test_echoes_text_message(
        self, client: TestClient, line_client_capturing: _CapturingClient
    ) -> None:
        payload = {
            "destination": "U_dest",
            "events": [_make_text_event(text="ゴミの日教えて")],
        }
        body = json.dumps(payload).encode("utf-8")
        resp = client.post(
            "/webhook",
            content=body,
            headers={
                "X-Line-Signature": _sign(body),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert line_client_capturing.replies == [("reply-1", ["ゴミの日教えて"])]

    def test_ignores_non_text_message(
        self, client: TestClient, line_client_capturing: _CapturingClient
    ) -> None:
        """Phase 1 では text 以外 (sticker / image / etc.) は無視 (200)。"""
        sticker_event = {
            "type": "message",
            "replyToken": "reply-x",
            "source": {"type": "user", "userId": "U_test"},
            "timestamp": 1700000000000,
            "mode": "active",
            "webhookEventId": "evt-2",
            "deliveryContext": {"isRedelivery": False},
            "message": {
                "type": "sticker",
                "id": "msg-2",
                "quoteToken": "qt-2",
                "packageId": "446",
                "stickerId": "1988",
                "stickerResourceType": "STATIC",
                "keywords": [],
            },
        }
        body = json.dumps({"events": [sticker_event]}).encode("utf-8")
        resp = client.post(
            "/webhook",
            content=body,
            headers={
                "X-Line-Signature": _sign(body),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert line_client_capturing.replies == []

    def test_handles_multiple_text_events_in_single_webhook(
        self, client: TestClient, line_client_capturing: _CapturingClient
    ) -> None:
        events = [
            _make_text_event(text="hello", reply_token="rt-a"),
            _make_text_event(text="world", reply_token="rt-b"),
        ]
        body = json.dumps({"events": events}).encode("utf-8")
        resp = client.post(
            "/webhook",
            content=body,
            headers={
                "X-Line-Signature": _sign(body),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert line_client_capturing.replies == [
            ("rt-a", ["hello"]),
            ("rt-b", ["world"]),
        ]
