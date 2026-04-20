"""POST /api/line/webhook — LINE Messaging API からのコールバックを処理する。

設計:
  - 認証情報 (LINE_CHANNEL_SECRET / LINE_CHANNEL_ACCESS_TOKEN) 未設定時は 503
  - 署名 (X-Line-Signature) 検証で失敗したら 401
  - イベントパース後、1 件ずつ `handle_event` に渡す。個別失敗はログのみで握りつぶし、
    LINE 側には常に 200 を返す (遅延・リトライが起きないようにするため)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from services.database import get_session_dep
from services.line_client import (
    InvalidSignatureError,
    LineBotClient,
    get_line_bot_client,
)
from services.line_handler import HandlerDeps, handle_event
from services.llm_client import LLMClient, get_llm_client
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/line", tags=["line"])


def _require_line_client() -> LineBotClient:
    client = get_line_bot_client()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "LINE integration is not configured "
                "(LINE_CHANNEL_SECRET / LINE_CHANNEL_ACCESS_TOKEN missing)"
            ),
        )
    return client


@router.post("/webhook")
async def line_webhook(
    request: Request,
    x_line_signature: str | None = Header(default=None, alias="X-Line-Signature"),
    session: AsyncSession = Depends(get_session_dep),
    llm: LLMClient = Depends(get_llm_client),
) -> dict[str, int]:
    line_client = _require_line_client()

    if not x_line_signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Line-Signature header",
        )

    body = await request.body()

    try:
        events = line_client.parse_events(body=body, signature=x_line_signature)
    except InvalidSignatureError as e:
        logger.warning("LINE webhook: invalid signature (%s)", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid LINE signature",
        ) from e

    deps = HandlerDeps(session=session, line_client=line_client, llm_client=llm)
    handled = 0
    for ev in events:
        try:
            await handle_event(ev, deps)
            handled += 1
        except Exception:
            # LINE 側のリトライを避けるため、個別エラーでも 200 を返す。
            # 例外本体はスタックごとログに残す。
            logger.exception("LINE event handler failed: %r", ev)

    logger.info("LINE webhook processed: received=%d handled=%d", len(events), handled)
    return {"received": len(events), "handled": handled}
