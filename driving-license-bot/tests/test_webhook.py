"""POST /webhook の統合テスト（FastAPI TestClient）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from importlib import reload

import pytest
from fastapi.testclient import TestClient

import app.config as config_module

CHANNEL_SECRET = "dummy-secret-1234567890"
CHANNEL_TOKEN = "dummy-access-token-abcdef"


def _sign(body: bytes) -> str:
    mac = hmac.new(CHANNEL_SECRET.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(mac).decode("utf-8")


def _build_app() -> TestClient:
    """env を変更したあと、依存モジュール群を正しい順序で reload する。

    順序: config → line_client → routes(health, line) → main。
    各モジュールの `from X import Y` 解決を確実にするため、トップダウンで reload。
    """
    reload(config_module)
    import app.main as main_module
    import app.routes.health as health_module
    import app.routes.line as line_module
    from app.services import line_client as line_client_module

    line_client_module.reset_line_bot_client()
    line_module.set_repo_bundle(None)
    line_module.set_question_pool(None)

    reload(line_client_module)
    reload(health_module)
    reload(line_module)
    reload(main_module)

    return TestClient(main_module.app)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("LINE_CHANNEL_SECRET", CHANNEL_SECRET)
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", CHANNEL_TOKEN)
    monkeypatch.setenv("LINE_CHANNEL_ID", "1234567890")
    return _build_app()


def test_healthz(client: TestClient) -> None:
    res = client.get("/healthz")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"


def test_webhook_returns_200_on_valid_signature(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LINE Reply API は monkeypatch でスタブ化、コアフローのみ検証。"""
    from app.services import line_client as line_client_module

    monkeypatch.setattr(
        line_client_module.LineBotClient,
        "reply_text",
        lambda self, reply_token, messages: None,
    )

    payload = {
        "destination": "Uxxxx",
        "events": [
            {
                "type": "message",
                "mode": "active",
                "timestamp": 1700000000000,
                "source": {"type": "user", "userId": "U" + "9" * 32},
                "webhookEventId": "01XYZ",
                "deliveryContext": {"isRedelivery": False},
                "replyToken": "rt-1",
                "message": {
                    "id": "1",
                    "type": "text",
                    "text": "ヘルプ",
                    "quoteToken": "qt-1",
                },
            }
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    res = client.post(
        "/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Line-Signature": _sign(body),
        },
    )
    assert res.status_code == 200
    assert res.json() == {"status": "accepted"}


def test_webhook_rejects_invalid_signature(client: TestClient) -> None:
    body = b'{"destination":"x","events":[]}'
    res = client.post(
        "/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Line-Signature": "invalid",
        },
    )
    assert res.status_code == 401


def test_webhook_503_when_line_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    c = _build_app()
    res = c.post(
        "/webhook",
        content=b"{}",
        headers={"Content-Type": "application/json", "X-Line-Signature": "x"},
    )
    assert res.status_code == 503


def test_signature_verification_unit() -> None:
    """`LineBotClient.verify_signature` 単体。"""
    from app.services.line_client import InvalidSignatureError, LineBotClient

    c = LineBotClient(channel_secret=CHANNEL_SECRET, channel_access_token=CHANNEL_TOKEN)
    body = b'{"x":1}'
    sig = _sign(body)
    c.verify_signature(body, sig)  # OK
    with pytest.raises(InvalidSignatureError):
        c.verify_signature(body, sig + "x")
    with pytest.raises(InvalidSignatureError):
        c.verify_signature(body, "")
