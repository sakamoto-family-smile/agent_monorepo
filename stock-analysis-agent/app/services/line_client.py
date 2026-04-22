"""LINE Messaging API / Webhook の薄いラッパー。

設計方針:
  - `line-bot-sdk` (v3) の細かい型をルート層に漏らさないため、必要最低限だけを
    `LineBotClient` 経由で公開する
  - テストは `StubLineBotClient` を `set_line_bot_client()` で差し込む
  - `LINE_CHANNEL_SECRET` / `LINE_CHANNEL_ACCESS_TOKEN` が未設定なら
    `build_default_line_bot_client()` は None を返す。ルート側でそれを見て
    503 を返す
  - 株価分析は数十秒〜分単位で完了するため、reply token の有効期限 (約1分) を
    超えるケースに備えて Push API (push_text / push_flex) も提供する
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


# 株価分析エージェントは画像・ファイル受信を扱わないので Text のみ対応。
LineEvent = LineTextEvent


# ---------------------------------------------------------------------------
# 例外 (SDK の例外を薄くラップ)
# ---------------------------------------------------------------------------


class InvalidSignatureError(Exception):
    """Webhook 署名検証に失敗した時に投げる。"""


# ---------------------------------------------------------------------------
# クライアント抽象
# ---------------------------------------------------------------------------


class LineBotClient(Protocol):
    """LINE Messaging API 呼出抽象。"""

    def parse_events(self, *, body: bytes, signature: str) -> list[LineEvent]:
        """署名検証 + イベントパース。失敗時は InvalidSignatureError を raise。"""

    async def reply_text(self, *, reply_token: str, text: str) -> None: ...

    async def reply_flex(
        self, *, reply_token: str, alt_text: str, contents: dict
    ) -> None: ...

    async def push_text(self, *, to: str, text: str) -> None: ...

    async def push_flex(self, *, to: str, alt_text: str, contents: dict) -> None: ...

    async def close(self) -> None: ...


# ---------------------------------------------------------------------------
# 実装: line-bot-sdk v3 ラッパー
# ---------------------------------------------------------------------------


class LineBotSdkClient:
    """line-bot-sdk v3 を使った本番実装。"""

    def __init__(self, *, channel_secret: str, channel_access_token: str) -> None:
        # 遅延 import — モジュールロード時に SDK が無くても失敗しないようにする
        from linebot.v3 import WebhookParser
        from linebot.v3.messaging import (
            AsyncApiClient,
            AsyncMessagingApi,
            Configuration,
        )

        self._parser = WebhookParser(channel_secret)
        config = Configuration(access_token=channel_access_token)
        self._api_client = AsyncApiClient(config)
        self._messaging = AsyncMessagingApi(self._api_client)

    def parse_events(self, *, body: bytes, signature: str) -> list[LineEvent]:
        from linebot.v3.exceptions import InvalidSignatureError as _SdkInvalidSignature
        from linebot.v3.webhooks import MessageEvent, TextMessageContent

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
            # 画像・スタンプ・ファイル等は現状無視
        return result

    @staticmethod
    def _trim_text(text: str, *, limit: int = 4900) -> str:
        if len(text) <= limit:
            return text
        return text[:limit] + "\n…（以下省略）"

    @staticmethod
    def _trim_alt(alt_text: str) -> str:
        # alt_text は LINE 上の通知プレビューや非対応クライアントで使われる (上限 400 文字)
        return alt_text[:400] or "(no alt)"

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

    async def reply_flex(
        self, *, reply_token: str, alt_text: str, contents: dict
    ) -> None:
        from linebot.v3.messaging import (
            FlexContainer,
            FlexMessage,
            ReplyMessageRequest,
        )

        if not reply_token:
            logger.warning("reply_flex called without reply_token; skipping")
            return
        container = FlexContainer.from_dict(contents)
        await self._messaging.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[FlexMessage(alt_text=self._trim_alt(alt_text), contents=container)],
            )
        )

    async def push_text(self, *, to: str, text: str) -> None:
        """reply token が切れた後の遅延通知に使う Push API。

        コスト課金対象 (LINE 公式アカウントの月間メッセージ数) になるので、
        呼び出し側で必要性を判断すること。
        """
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

    async def push_flex(self, *, to: str, alt_text: str, contents: dict) -> None:
        from linebot.v3.messaging import (
            FlexContainer,
            FlexMessage,
            PushMessageRequest,
        )

        if not to:
            logger.warning("push_flex called without target user_id; skipping")
            return
        container = FlexContainer.from_dict(contents)
        await self._messaging.push_message(
            PushMessageRequest(
                to=to,
                messages=[FlexMessage(alt_text=self._trim_alt(alt_text), contents=container)],
            )
        )

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
    """テスト・起動時差し替え用 setter。"""
    global _default_client, _build_attempted
    _default_client = client
    _build_attempted = client is not None
