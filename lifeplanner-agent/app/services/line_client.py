"""LINE Messaging API / Webhook の薄いラッパー。

設計方針:
  - `line-bot-sdk` (v3) の細かい型をルート層に漏らさないため、必要最低限だけを
    `LineBotClient` 経由で公開する
  - テストは `StubLineBotClient` を `set_line_bot_client()` で差し込む
  - `LINE_CHANNEL_SECRET` / `LINE_CHANNEL_ACCESS_TOKEN` が未設定なら
    `build_default_line_bot_client()` は None を返す。ルート側でそれを見て
    503 を返す。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# イベントモデル (SDK 型への依存をルート層に漏らさないための内製 DTO)
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
    file_name: str
    file_size: int


LineEvent = LineTextEvent | LineFileEvent


# ---------------------------------------------------------------------------
# クライアント抽象
# ---------------------------------------------------------------------------


class LineBotClient(Protocol):
    """LINE Messaging API 呼出抽象。"""

    def parse_events(self, *, body: bytes, signature: str) -> list[LineEvent]:
        """署名検証 + イベントパース。失敗時は InvalidSignatureError を raise。"""

    async def reply_text(self, *, reply_token: str, text: str) -> None: ...

    async def get_message_content(self, *, message_id: str) -> bytes: ...

    async def close(self) -> None: ...


# ---------------------------------------------------------------------------
# 例外 (SDK の例外を薄くラップ)
# ---------------------------------------------------------------------------


class InvalidSignatureError(Exception):
    """Webhook 署名検証に失敗した時に投げる。"""


# ---------------------------------------------------------------------------
# 実装: line-bot-sdk v3 ラッパー
# ---------------------------------------------------------------------------


class LineBotSdkClient:
    """line-bot-sdk v3 を使った本番実装。"""

    def __init__(self, *, channel_secret: str, channel_access_token: str) -> None:
        # 遅延 import — モジュールロード時に SDK が無くても失敗しないようにする。
        from linebot.v3 import WebhookParser
        from linebot.v3.messaging import (
            AsyncApiClient,
            AsyncMessagingApi,
            AsyncMessagingApiBlob,
            Configuration,
        )

        self._parser = WebhookParser(channel_secret)
        config = Configuration(access_token=channel_access_token)
        self._api_client = AsyncApiClient(config)
        self._messaging = AsyncMessagingApi(self._api_client)
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
                # グループ・ルーム・userId 非同意などはスキップ
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
                        file_name=msg.file_name or "unnamed",
                        file_size=int(msg.file_size or 0),
                    )
                )
            # 画像・スタンプ等は現状無視
        return result

    async def reply_text(self, *, reply_token: str, text: str) -> None:
        from linebot.v3.messaging import ReplyMessageRequest, TextMessage

        if not reply_token:
            # push API 相当に切り替える余地はあるが、MVP は reply のみ
            logger.warning("reply_text called without reply_token; skipping")
            return
        # LINE の文字数上限 (5000) を超えると API エラーになるため念のため切り詰め
        trimmed = text if len(text) <= 4900 else text[:4900] + "\n…（以下省略）"
        await self._messaging.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=trimmed)],
            )
        )

    async def get_message_content(self, *, message_id: str) -> bytes:
        # AsyncMessagingApiBlob.get_message_content は bytearray を返す
        data = await self._blob.get_message_content(message_id=message_id)
        return bytes(data)

    async def close(self) -> None:
        await self._api_client.close()


# ---------------------------------------------------------------------------
# DI ファクトリ
# ---------------------------------------------------------------------------


_default_client: LineBotClient | None = None
_build_attempted: bool = False


def build_default_line_bot_client() -> LineBotClient | None:
    """config から実クライアントを構築。認証情報が無ければ None。"""
    if not settings.line_channel_secret or not settings.line_channel_access_token:
        logger.warning(
            "LINE_CHANNEL_SECRET or LINE_CHANNEL_ACCESS_TOKEN not set; "
            "LINE webhook will respond 503"
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
    """テスト・起動時差し替え用 setter。"""
    global _default_client, _build_attempted
    _default_client = client
    _build_attempted = client is not None
