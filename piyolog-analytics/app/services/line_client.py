"""LINE Messaging API の薄いラッパ。

stock-analysis-agent 流儀を踏襲しつつ、ぴよログ固有の差分:
  - `FileMessage` を扱う (`.txt` 添付の取り込み)
  - content API からメッセージ本体 (bytes) をダウンロードする `fetch_message_content()` を公開
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class LinePostbackEvent:
    """リッチメニュー / クイックリプライ等から飛んでくる Postback イベント。

    `data` は URL クエリ風の文字列 (例: `action=chart&kind=milk&period=week`)。
    `params` は datetime picker 等から付与されるユーザー選択値 (例:
    `{"date": "2025-08-15"}`)。Postback Router 側で解析する。
    """

    event_type: str  # "postback"
    line_user_id: str
    reply_token: str
    data: str
    params: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class QuickReplyAction:
    """LINE Quick Reply の 1 ボタン仕様。

    `kind="postback"` は固定 `data` を送る。`kind="datetimepicker"` は
    ユーザーが選んだ日付 / 時刻を `params` 付きの postback で返す
    (LINE 仕様: action.type=datetimepicker, mode=date|time|datetime)。
    """

    kind: str  # "postback" | "datetimepicker"
    label: str
    data: str
    mode: str = "date"  # datetimepicker のみ
    initial: str | None = None
    max_value: str | None = None
    min_value: str | None = None


@dataclass(frozen=True)
class LineFollowEvent:
    """友だち追加イベント (Phase 2 で Welcome メッセージ + リッチメニュー紐付け)。"""

    event_type: str  # "follow"
    line_user_id: str
    reply_token: str


LineEvent = LineTextEvent | LineFileEvent | LinePostbackEvent | LineFollowEvent


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

    async def reply_text(
        self,
        *,
        reply_token: str,
        text: str,
        quick_reply: list[QuickReplyAction] | None = None,
    ) -> None: ...

    async def reply_image(
        self, *, reply_token: str, image_url: str, preview_url: str | None = None
    ) -> None: ...

    async def push_text(self, *, to: str, text: str) -> None: ...

    async def push_image(
        self, *, to: str, image_url: str, preview_url: str | None = None
    ) -> None: ...

    async def fetch_message_content(self, *, message_id: str) -> bytes: ...

    # Phase 2 リッチメニュー: per-user の link/unlink (mode 切替時に使う)
    async def link_richmenu_to_user(self, *, user_id: str, rich_menu_id: str) -> None: ...

    async def unlink_richmenu_from_user(self, *, user_id: str) -> None: ...

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
            FollowEvent,
            MessageEvent,
            PostbackEvent,
            TextMessageContent,
        )

        try:
            raw_events = self._parser.parse(body.decode("utf-8"), signature)
        except _SdkInvalidSignature as e:
            raise InvalidSignatureError(str(e)) from e

        result: list[LineEvent] = []
        for ev in raw_events:
            source = getattr(ev, "source", None)
            user_id = getattr(source, "user_id", None) if source else None
            if not user_id:
                continue
            reply_token = getattr(ev, "reply_token", "") or ""

            if isinstance(ev, MessageEvent):
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
                continue

            if isinstance(ev, PostbackEvent):
                postback = getattr(ev, "postback", None)
                data = getattr(postback, "data", "") if postback else ""
                params_obj = getattr(postback, "params", None) if postback else None
                params: dict[str, str] = {}
                if params_obj is not None:
                    # SDK は属性 (model) または dict のいずれか。両対応。
                    for key in ("date", "time", "datetime"):
                        val = (
                            params_obj.get(key)
                            if isinstance(params_obj, dict)
                            else getattr(params_obj, key, None)
                        )
                        if val:
                            params[key] = str(val)
                result.append(
                    LinePostbackEvent(
                        event_type="postback",
                        line_user_id=user_id,
                        reply_token=reply_token,
                        data=data or "",
                        params=params,
                    )
                )
                continue

            if isinstance(ev, FollowEvent):
                result.append(
                    LineFollowEvent(
                        event_type="follow",
                        line_user_id=user_id,
                        reply_token=reply_token,
                    )
                )
                continue
        return result

    @staticmethod
    def _trim_text(text: str, *, limit: int = 4900) -> str:
        if len(text) <= limit:
            return text
        return text[:limit] + "\n…(以下省略)"

    async def reply_text(
        self,
        *,
        reply_token: str,
        text: str,
        quick_reply: list[QuickReplyAction] | None = None,
    ) -> None:
        from linebot.v3.messaging import ReplyMessageRequest, TextMessage

        if not reply_token:
            logger.warning("reply_text called without reply_token; skipping")
            return
        message = TextMessage(text=self._trim_text(text))
        if quick_reply:
            message.quick_reply = self._build_quick_reply(quick_reply)
        await self._messaging.reply_message(
            ReplyMessageRequest(reply_token=reply_token, messages=[message])
        )

    @staticmethod
    def _build_quick_reply(actions: list[QuickReplyAction]):
        """QuickReplyAction (DTO) → SDK QuickReply 構造体への変換。

        LINE 仕様で 1 トーク内に最大 13 アイテム。本アプリでは 3〜4 個しか
        使わないので length 制約のチェックは省略 (将来拡張時に追加)。
        """
        from linebot.v3.messaging import (
            DatetimePickerAction,
            PostbackAction,
            QuickReply,
            QuickReplyItem,
        )

        items = []
        for a in actions:
            if a.kind == "datetimepicker":
                action = DatetimePickerAction(
                    type="datetimepicker",
                    label=a.label,
                    data=a.data,
                    mode=a.mode,
                    initial=a.initial,
                    max=a.max_value,
                    min=a.min_value,
                )
            elif a.kind == "postback":
                action = PostbackAction(
                    type="postback",
                    label=a.label,
                    data=a.data,
                    display_text=a.label,
                )
            else:
                logger.warning("unknown QuickReplyAction kind: %s", a.kind)
                continue
            items.append(QuickReplyItem(type="action", action=action))
        return QuickReply(items=items)

    async def reply_image(
        self, *, reply_token: str, image_url: str, preview_url: str | None = None
    ) -> None:
        from linebot.v3.messaging import ImageMessage, ReplyMessageRequest

        if not reply_token:
            logger.warning("reply_image called without reply_token; skipping")
            return
        await self._messaging.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[
                    ImageMessage(
                        original_content_url=image_url,
                        preview_image_url=preview_url or image_url,
                    )
                ],
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

    async def push_image(self, *, to: str, image_url: str, preview_url: str | None = None) -> None:
        from linebot.v3.messaging import ImageMessage, PushMessageRequest

        if not to:
            logger.warning("push_image called without target user_id; skipping")
            return
        await self._messaging.push_message(
            PushMessageRequest(
                to=to,
                messages=[
                    ImageMessage(
                        original_content_url=image_url,
                        preview_image_url=preview_url or image_url,
                    )
                ],
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

    async def link_richmenu_to_user(self, *, user_id: str, rich_menu_id: str) -> None:
        """per-user に rich menu を紐付け (consulting mode 切替時)。"""
        if not user_id or not rich_menu_id:
            logger.warning("link_richmenu skipped (empty user_id/rich_menu_id)")
            return
        await self._messaging.link_rich_menu_id_to_user(user_id=user_id, rich_menu_id=rich_menu_id)

    async def unlink_richmenu_from_user(self, *, user_id: str) -> None:
        """per-user の rich menu 紐付けを解除 (default rich menu に戻る)。"""
        if not user_id:
            logger.warning("unlink_richmenu skipped (empty user_id)")
            return
        await self._messaging.unlink_rich_menu_id_from_user(user_id=user_id)

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
