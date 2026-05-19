"""POST /webhook — LINE Messaging API のコールバック (Phase 1: echo reply)。

Phase 1 の挙動:
- 即時 200 OK を返す
- 署名検証失敗で 401
- LINE_* env 未設定で 503
- text MessageEvent には同じ本文を echo reply
- それ以外のイベント (follow / sticker / image / etc.) は今は無視 (200)

Phase 2 以降で Intent Agent / RAG Agent が呼ばれる流れに置き換わる。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, Request, status
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from app.line_client import InvalidSignatureError, get_line_bot_client

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhook")
async def webhook(
    request: Request,
    x_line_signature: str = Header(default=""),
) -> dict[str, str]:
    """LINE Platform からの webhook を受け取り、 即時 200 を返す。"""
    client = get_line_bot_client()
    if client is None:
        # LINE_* env 未設定 (Phase 0 状態 / 開発前)。 503 で運用に気づける状態にする。
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LINE channel is not configured",
        )

    body = await request.body()
    try:
        events = client.parse_events(body, x_line_signature)
    except InvalidSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid signature"
        ) from None

    for event in events:
        try:
            _handle_event(client, event)
        except Exception:  # pragma: no cover - 個別 event 失敗は LINE 側を blocking しない
            logger.exception("error while handling LINE event: %r", event)

    return {"status": "ok"}


def _handle_event(client, event) -> None:
    """Phase 1: text MessageEvent のみ echo reply。 他は無視。"""
    if not isinstance(event, MessageEvent):
        return
    message = event.message
    if not isinstance(message, TextMessageContent):
        return
    reply_token = event.reply_token
    if not reply_token:
        return
    client.reply_text(reply_token, [message.text])


__all__ = ["router"]
