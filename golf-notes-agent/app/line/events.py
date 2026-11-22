"""Webhook の署名検証とイベントの読み取り。

line-bot-sdk の型に頼らず、届いた JSON をそのまま原本として残せるよう dict のまま扱う。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any


class InvalidSignatureError(Exception):
    """X-Line-Signature が本文と合わない。"""


def signature(body: bytes, channel_secret: str) -> str:
    digest = hmac.new(channel_secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def verify(body: bytes, header: str | None, channel_secret: str) -> None:
    if not channel_secret or not header:
        raise InvalidSignatureError("missing secret or signature")
    try:
        expected = signature(body, channel_secret).encode("ascii")
        given = header.encode("ascii")
    except UnicodeEncodeError as e:
        raise InvalidSignatureError("non-ascii signature") from e
    if not hmac.compare_digest(expected, given):
        raise InvalidSignatureError("signature mismatch")


@dataclass(frozen=True)
class LineEvent:
    webhook_event_id: str
    type: str  # message | postback | follow | unfollow | ...
    user_id: str | None
    reply_token: str | None
    timestamp_ms: int
    is_redelivery: bool
    raw: dict[str, Any]
    message_id: str | None = None
    message_type: str | None = None  # text | image | video | audio | file | sticker | location
    text: str | None = None
    postback_data: str | None = None
    content_provider: str | None = None  # line | external
    duration_ms: int | None = None


def parse_body(body: bytes) -> list[LineEvent]:
    data = json.loads(body.decode("utf-8"))
    return [parse_event(ev) for ev in data.get("events", []) if ev.get("webhookEventId")]


def parse_event(ev: dict[str, Any]) -> LineEvent:
    source = ev.get("source") or {}
    # 1:1 のトーク以外 (グループ・ルーム) は userId があっても扱わない
    user_id = source.get("userId") if source.get("type") == "user" else None
    message = ev.get("message") or {}
    postback = ev.get("postback") or {}
    provider = message.get("contentProvider") or {}
    return LineEvent(
        webhook_event_id=ev["webhookEventId"],
        type=ev.get("type", ""),
        user_id=user_id,
        reply_token=ev.get("replyToken"),
        timestamp_ms=int(ev.get("timestamp", 0)),
        is_redelivery=bool((ev.get("deliveryContext") or {}).get("isRedelivery")),
        raw=ev,
        message_id=message.get("id"),
        message_type=message.get("type"),
        text=message.get("text"),
        postback_data=postback.get("data"),
        content_provider=provider.get("type"),
        duration_ms=message.get("duration"),
    )
