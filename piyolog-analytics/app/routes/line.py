"""POST /api/line/webhook — LINE Messaging API からのコールバックを処理する。

- 認証情報未設定時 503
- X-Line-Signature 検証失敗で 401
- 個別イベントの失敗は握りつぶしてログのみ (LINE の再送を抑止するため常に 200)
- バックグラウンド job は FastAPI BackgroundTasks に載せる (LINE 3 秒応答の遵守)
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from analytics_platform.observability.hashing import sha256_prefixed
from config import settings
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status
from instrumentation import get_analytics_logger
from repositories.event_repo import EventRepo
from services.line_client import (
    InvalidSignatureError,
    LineBotClient,
    get_line_bot_client,
)
from services.line_handler import HandlerDeps, handle_event

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/line", tags=["line"])


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


def _make_scheduler(
    background_tasks: BackgroundTasks,
) -> Callable[[Callable[[], Awaitable[None]]], None]:
    def _schedule(factory: Callable[[], Awaitable[None]]) -> None:
        async def _wrapper() -> None:
            try:
                await factory()
            except Exception:
                logger.exception("LINE background task failed")

        background_tasks.add_task(_wrapper)

    return _schedule


_repo_singleton: EventRepo | None = None


def get_repo() -> EventRepo:
    """プロセス内 EventRepo シングルトン (テストで差し替え可)。

    `DATABASE_URL` 優先、未設定なら `PIYOLOG_DB_PATH` から SQLite URL を生成。
    """
    global _repo_singleton
    if _repo_singleton is None:
        _repo_singleton = EventRepo(database_url=settings.resolved_database_url)
    return _repo_singleton


def set_repo(repo: EventRepo | None) -> None:
    global _repo_singleton
    _repo_singleton = repo


@router.post("/webhook")
async def line_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_line_signature: str | None = Header(default=None, alias="X-Line-Signature"),
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

    al = get_analytics_logger()
    session_id = f"line_{uuid.uuid4().hex[:16]}"
    body_hash = sha256_prefixed(body.decode("utf-8", errors="replace"))

    al.emit(
        event_type="conversation_event",
        event_version="1.0.0",
        severity="INFO",
        fields={
            "conversation_phase": "started",
            "agent_id": settings.analytics_service_name,
            "initial_query_hash": body_hash,
        },
        session_id=session_id,
    )

    repo = get_repo()
    await repo.initialize()
    deps = HandlerDeps(
        line_client=line_client,
        repo=repo,
        family_id=settings.family_id,
        family_user_ids=settings.family_user_id_set,
        default_child_id=settings.default_child_id,
        upload_max_bytes=settings.upload_max_bytes,
        schedule_background=_make_scheduler(background_tasks),
        now_factory=lambda: datetime.now(UTC),
    )

    handled = 0
    failed = 0
    for ev in events:
        try:
            await handle_event(ev, deps)
            handled += 1
        except Exception as exc:
            logger.exception("LINE event handler failed: %r", ev)
            failed += 1
            try:
                al.emit(
                    event_type="error_event",
                    event_version="1.0.0",
                    severity="ERROR",
                    fields={
                        "error_type": type(exc).__name__,
                        "error_message": str(exc)[:1000],
                        "error_category": "internal",
                        "is_retriable": False,
                    },
                    session_id=session_id,
                )
            except Exception:
                logger.exception("failed to emit LINE error_event")

    logger.info(
        "LINE webhook processed: received=%d handled=%d failed=%d",
        len(events), handled, failed,
    )

    al.emit(
        event_type="business_event",
        event_version="1.0.0",
        severity="INFO",
        fields={
            "business_domain": "piyolog",
            "action": "line_webhook_processed",
            "resource_type": "webhook",
            "resource_id": session_id,
            "attributes": {
                "received": len(events),
                "handled": handled,
                "failed": failed,
            },
        },
        session_id=session_id,
    )
    al.emit(
        event_type="conversation_event",
        event_version="1.0.0",
        severity="INFO",
        fields={
            "conversation_phase": "ended",
            "agent_id": settings.analytics_service_name,
            "initial_query_hash": body_hash,
        },
        session_id=session_id,
    )
    await al.flush()

    return {"received": len(events), "handled": handled}
