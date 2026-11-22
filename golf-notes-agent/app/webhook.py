"""POST /api/line/webhook — LINE からのイベントを受ける (Funnel で公開するのはここだけ)。

- 署名が合わなければ 401。許可リストにない userId は黙って捨てる (返事もしない)
- イベントは原本を先に保存し、同じ webhookEventId は 2 回目以降を処理しない
- 1 件の処理に失敗しても、ほかのイベントは続け、LINE には 200 を返す (再送の嵐を防ぐ)
- reply はレスポンスを返したあとに送る。再送されたイベントには reply しない
  (reply トークンが使えないため。保存はする)
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status

from app.deps import Deps
from app.handlers import dispatch
from app.line.events import InvalidSignatureError, LineEvent, parse_body, verify
from app.storage.raw import save_raw

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/line")


def _user_hash(user_id: str | None) -> str:
    return hashlib.sha256((user_id or "").encode()).hexdigest()[:12]


async def _reply(deps: Deps, reply_token: str, messages: list[dict[str, Any]]) -> None:
    try:
        # 1 回の reply で送れるのは 5 件まで
        await deps.line.reply(reply_token, messages[:5])
    except Exception:  # 返事の失敗で保存済みのデータは変わらない
        logger.exception("LINE reply failed")


async def _process(deps: Deps, ev: LineEvent) -> list[dict[str, Any]]:
    now = deps.clock()
    async with deps.engine.begin() as conn:
        raw_id = await save_raw(conn, deps.settings.paths, ev, now, deps.settings.tz)
        if raw_id is None:
            logger.info("duplicate event skipped: %s", ev.webhook_event_id)
            return []
        return await dispatch.handle(
            dispatch.Context(deps=deps, conn=conn, ev=ev, raw_event_id=raw_id, now=now)
        )


@router.post("/webhook")
async def webhook(
    request: Request,
    background: BackgroundTasks,
    x_line_signature: str | None = Header(default=None, alias="X-Line-Signature"),
) -> dict[str, str]:
    deps: Deps = request.app.state.deps
    secret = deps.settings.line_channel_secret
    if not secret or not deps.settings.line_channel_access_token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "LINE is not configured")
    body = await request.body()
    try:
        verify(body, x_line_signature, secret)
    except InvalidSignatureError as e:
        logger.warning("invalid LINE signature")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid signature") from e

    for ev in parse_body(body):
        if ev.user_id is None or ev.user_id not in deps.settings.allowed_user_ids:
            logger.info("dropped event from non-allowed source (user=%s)", _user_hash(ev.user_id))
            continue
        try:
            messages = await _process(deps, ev)
        except Exception:  # 1 件の失敗で残りのイベントを落とさない
            logger.exception("failed to handle event %s", ev.webhook_event_id)
            continue
        if messages and ev.reply_token and not ev.is_redelivery:
            background.add_task(_reply, deps, ev.reply_token, messages)
    return {}
