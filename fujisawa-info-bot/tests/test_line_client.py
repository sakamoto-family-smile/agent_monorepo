"""LineBotClient の単体テスト (Phase 1)。

`verify_signature` の HMAC-SHA256 検証パスを直接叩く。 LINE 公式 SDK の API client は
`reset_line_bot_client` でシングルトンをリセットしながら check する。
"""

from __future__ import annotations

import base64
import hashlib
import hmac

import pytest

from app import line_client
from app.line_client import (
    InvalidSignatureError,
    LineBotClient,
    get_line_bot_client,
    reset_line_bot_client,
)

_SECRET = "test-channel-secret"
_TOKEN = "test-channel-access-token"


def _sign(body: bytes, secret: str = _SECRET) -> str:
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(mac).decode("utf-8")


class TestVerifySignature:
    def test_accepts_valid_signature(self) -> None:
        client = LineBotClient(channel_secret=_SECRET, channel_access_token=_TOKEN)
        body = b'{"events": []}'
        client.verify_signature(body, _sign(body))

    def test_rejects_empty_signature(self) -> None:
        client = LineBotClient(channel_secret=_SECRET, channel_access_token=_TOKEN)
        with pytest.raises(InvalidSignatureError):
            client.verify_signature(b'{"events": []}', "")

    def test_rejects_mismatched_signature(self) -> None:
        client = LineBotClient(channel_secret=_SECRET, channel_access_token=_TOKEN)
        body = b'{"events": []}'
        wrong = _sign(body, secret="other-secret")
        with pytest.raises(InvalidSignatureError):
            client.verify_signature(body, wrong)

    def test_rejects_body_tampering(self) -> None:
        client = LineBotClient(channel_secret=_SECRET, channel_access_token=_TOKEN)
        original = b'{"events": [{"type": "message"}]}'
        sig = _sign(original)
        tampered = b'{"events": [{"type": "follow"}]}'
        with pytest.raises(InvalidSignatureError):
            client.verify_signature(tampered, sig)


class TestConstructorValidation:
    def test_requires_both_credentials(self) -> None:
        with pytest.raises(ValueError):
            LineBotClient(channel_secret="", channel_access_token=_TOKEN)
        with pytest.raises(ValueError):
            LineBotClient(channel_secret=_SECRET, channel_access_token="")


class TestSingleton:
    def setup_method(self) -> None:
        reset_line_bot_client()

    def teardown_method(self) -> None:
        reset_line_bot_client()

    def test_returns_none_when_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(line_client.settings, "line_channel_secret", "", raising=False)
        monkeypatch.setattr(
            line_client.settings, "line_channel_access_token", "", raising=False
        )
        assert get_line_bot_client() is None

    def test_returns_singleton_when_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(line_client.settings, "line_channel_secret", _SECRET, raising=False)
        monkeypatch.setattr(
            line_client.settings, "line_channel_access_token", _TOKEN, raising=False
        )
        a = get_line_bot_client()
        b = get_line_bot_client()
        assert a is not None
        assert a is b
