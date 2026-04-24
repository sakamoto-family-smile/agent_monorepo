"""LINE Messaging API の薄いラッパ。

stock-analysis-agent 流儀を踏襲しつつ、ぴよログ固有の差分:
  - `FileMessage` を扱う (`.txt` 添付の取り込み)
  - content API からメッセージ本体 (bytes) をダウンロードする `fetch_message_content()` を公開
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DTO (SDK 型をルート層に漏らさない)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LineTextEvent:
    event_type: str  # "text"
    line_user_id: str
    reply_token: str
    text: str


@dataclass(frozen=True)
class LineFileEvent:
    event_type: str  # "file"
    line_user_id: str
    reply_token: str
    message_id: str
    filename: str
    file_size: int


LineEvent = LineTextEvent | LineFileEvent


# ---------------------------------------------------------------------------
# 例外
# ---------------------------------------------------------------------------


class InvalidSignatureError(Exception):
    """Webhook 署名検証に失敗した時に投げる。"""


# ---------------------------------------------------------------------------
# クライアント抽象
# ---------------------------------------------------------------------------


class LineBotClient(Protocol):
    def parse_events(self, *, body: bytes, signature: str) -> list[LineEvent]: ...

    async def reply_text(self, *, reply_token: str, text: str) -> None: ...

    async def push_text(self, *, to: str, text: str) -> None: ...

    async def fetch_message_content(self, *, message_id: str) -> bytes: ...

    async def close(self) -> None: ...


# ---------------------------------------------------------------------------
# 実装: line-bot-sdk v3
# ---------------------------------------------------------------------------


class LineBotSdkClient:
    def __init__(self, *, channel_secret: str, channel_access_token: str) -> None:
        from linebot.v3 import WebhookParser
        from linebot.v3.messaging import (
            AsyncApiClient,
            AsyncMessagingApi,
            AsyncMessagingApiBlob,
            Configuration,
        )

        self._parser = WebhookParser(channel_secret)
        self._config = Configuration(access_token=channel_access_token)
        self._api_client = AsyncApiClient(self._config)
        self._messaging = AsyncMessagingApi(self._api_client)
        # MessagingApiBlob はメディアコンテンツ取得用の別 API
        self._blob = AsyncMessagingApiBlob(self._api_client)

    def parse_events(self, *, body: bytes, signature: str) -> list[LineEvent]:
        from linebot.v3.exceptions import InvalidSignatureError as _SdkInvalidSignature
        from linebot.v3.webhooks import (
            FileMessageContent,
            MessageEvent,
            TextMessageContent,
        )

        try:
            raw_events = self._parser.parse(body.decode("utf-8"), signature)
        except _SdkInvalidSignature as e:
            raise InvalidSignatureError(str(e)) from e

        result: list[LineEvent] = []
        for ev in raw_events:
            if not isinstance(ev, MessageEvent):
                continue
            source = getattr(ev, "source", None)
            user_id = getattr(source, "user_id", None) if source else None
            if not user_id:
                continue
            reply_token = getattr(ev, "reply_token", "") or ""
            msg = ev.message
            if isinstance(msg, TextMessageContent):
                result.append(
                    LineTextEvent(
                        event_type="text",
                        line_user_id=user_id,
                        reply_token=reply_token,
                        text=msg.text or "",
                    )
                )
            elif isinstance(msg, FileMessageContent):
                result.append(
                    LineFileEvent(
                        event_type="file",
                        line_user_id=user_id,
                        reply_token=reply_token,
                        message_id=msg.id,
                        filename=msg.file_name or "",
                        file_size=int(msg.file_size or 0),
                    )
                )
        return result

    @staticmethod
    def _trim_text(text: str, *, limit: int = 4900) -> str:
        if len(text) <= limit:
            return text
        return text[:limit] + "\n…(以下省略)"

    async def reply_text(self, *, reply_token: str, text: str) -> None:
        from linebot.v3.messaging import ReplyMessageRequest, TextMessage

        if not reply_token:
            logger.warning("reply_text called without reply_token; skipping")
            return
        await self._messaging.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=self._trim_text(text))],
            )
        )

    async def push_text(self, *, to: str, text: str) -> None:
        from linebot.v3.messaging import PushMessageRequest, TextMessage

        if not to:
            logger.warning("push_text called without target user_id; skipping")
            return
        await self._messaging.push_message(
            PushMessageRequest(
                to=to,
                messages=[TextMessage(text=self._trim_text(text))],
            )
        )

    async def fetch_message_content(self, *, message_id: str) -> bytes:
        """メディアメッセージ (ファイル添付) の生バイトを取得する。

        LINE SDK v3 は `AsyncMessagingApiBlob.get_message_content` が
        `tempfile._TemporaryFileWrapper` などファイルライクを返す実装になっている
        ので、都度 bytes に寄せる。
        """
        resp = await self._blob.get_message_content(message_id=message_id)
        # SDK バージョンによって tempfile / bytes どちらも返しうるので両対応
        if isinstance(resp, bytes):
            return resp
        if hasattr(resp, "read"):
            data = resp.read()
            if isinstance(data, bytes):
                return data
        return bytes(resp)

    async def close(self) -> None:
        await self._api_client.close()


# ---------------------------------------------------------------------------
# DI ファクトリ
# ---------------------------------------------------------------------------


_default_client: LineBotClient | None = None
_build_attempted: bool = False


def build_default_line_bot_client() -> LineBotClient | None:
    if not settings.line_channel_secret or not settings.line_channel_access_token:
        logger.warning(
            "LINE_CHANNEL_SECRET or LINE_CHANNEL_ACCESS_TOKEN not set; "
            "/api/line/webhook will respond 503"
        )
        return None
    return LineBotSdkClient(
        channel_secret=settings.line_channel_secret,
        channel_access_token=settings.line_channel_access_token,
    )


def get_line_bot_client() -> LineBotClient | None:
    global _default_client, _build_attempted
    if _default_client is None and not _build_attempted:
        _default_client = build_default_line_bot_client()
        _build_attempted = True
    return _default_client


def set_line_bot_client(client: LineBotClient | None) -> None:
    global _default_client, _build_attempted
    _default_client = client
    _build_attempted = client is not None
