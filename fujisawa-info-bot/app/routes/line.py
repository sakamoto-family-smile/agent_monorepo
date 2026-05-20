"""POST /webhook — LINE Messaging API のコールバック。

Phase 2 の挙動:
- 即時 200 OK を返す
- 署名検証失敗で 401
- LINE_* env 未設定で 503
- text MessageEvent は LangGraph (Intent → RAG) を実行して結果を reply
- それ以外のイベント (follow / sticker / image / etc.) は無視 (200)

Phase 3 で Pub/Sub 経由の非同期化に置き換える (LINE 3 秒タイムアウト対策)。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, Request, status
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from app.graph import GraphDependencies, run_graph
from app.line_client import InvalidSignatureError, LineBotClient, get_line_bot_client

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

    deps: GraphDependencies = request.app.state.graph_deps
    for event in events:
        try:
            await _handle_event(client, event, deps)
        except Exception:  # pragma: no cover - 個別 event 失敗は LINE 側を blocking しない
            logger.exception("error while handling LINE event: %r", event)

    return {"status": "ok"}


async def _handle_event(
    client: LineBotClient,
    event: object,
    deps: GraphDependencies,
) -> None:
    """Phase 2: text MessageEvent → LangGraph 実行 → reply。 他は無視。"""
    if not isinstance(event, MessageEvent):
        return
    message = event.message
    if not isinstance(message, TextMessageContent):
        return
    reply_token = event.reply_token
    if not reply_token:
        return
    user_id = event.source.user_id if event.source else "unknown"
    answer = await run_graph(deps=deps, user_id=user_id, query=message.text)
    client.reply_text(reply_token, [answer])


__all__ = ["router"]
