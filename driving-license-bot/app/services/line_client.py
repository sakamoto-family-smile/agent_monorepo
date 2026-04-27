"""LINE Messaging API クライアントと Webhook 署名検証。

`line-bot-sdk` v3 を薄くラップする。Phase 1 では Reply Message のみ使用。
Push Message は Phase 5 のリマインダー実装時に追加する。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging

from linebot.v3.exceptions import InvalidSignatureError as _SDKInvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhook import WebhookParser
from linebot.v3.webhooks import MessageEvent
from linebot.v3.webhooks.models import Event

from app.config import settings

logger = logging.getLogger(__name__)


class InvalidSignatureError(Exception):
    """LINE 署名検証失敗。"""


_client_singleton: LineBotClient | None = None


def get_line_bot_client() -> LineBotClient | None:
    """グローバルシングルトン。`LINE_*` env 未設定時は None。"""
    global _client_singleton
    if _client_singleton is not None:
        return _client_singleton
    if not settings.line_configured:
        return None
    _client_singleton = LineBotClient(
        channel_secret=settings.line_channel_secret,
        channel_access_token=settings.line_channel_access_token,
    )
    return _client_singleton


def reset_line_bot_client() -> None:
    """テスト用シングルトンリセット。"""
    global _client_singleton
    _client_singleton = None


class LineBotClient:
    def __init__(self, *, channel_secret: str, channel_access_token: str) -> None:
        if not channel_secret or not channel_access_token:
            raise ValueError("channel_secret / channel_access_token are required")
        self._channel_secret = channel_secret
        self._configuration = Configuration(access_token=channel_access_token)
        self._parser = WebhookParser(channel_secret)

    def verify_signature(self, body: bytes, signature: str) -> None:
        """LINE 公式署名仕様に従い、HMAC-SHA256 で検証する。

        SDK の WebhookParser も内部で同じ検証を行うが、bytes 直の検証パスを残し
        テスト容易性を上げる。
        """
        if not signature:
            raise InvalidSignatureError("missing signature header")
        mac = hmac.new(
            self._channel_secret.encode("utf-8"), body, hashlib.sha256
        ).digest()
        expected = base64.b64encode(mac).decode("utf-8")
        if not hmac.compare_digest(expected, signature):
            raise InvalidSignatureError("signature mismatch")

    def parse_events(self, body: bytes, signature: str) -> list[Event]:
        """署名検証 + パース。"""
        try:
            return self._parser.parse(body.decode("utf-8"), signature)
        except _SDKInvalidSignatureError as exc:
            raise InvalidSignatureError(str(exc)) from exc

    def reply_text(self, reply_token: str, messages: list[str]) -> None:
        """複数行のテキスト Reply Message。"""
        if not messages:
            return
        line_messages = [TextMessage(text=m) for m in messages[:5]]  # LINE 制限 5 通/回
        with ApiClient(self._configuration) as api_client:
            api = MessagingApi(api_client)
            api.reply_message(
                ReplyMessageRequest(reply_token=reply_token, messages=line_messages)
            )


__all__ = [
    "InvalidSignatureError",
    "LineBotClient",
    "MessageEvent",
    "get_line_bot_client",
    "reset_line_bot_client",
]
