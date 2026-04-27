"""POST /webhook — LINE Messaging API のコールバック。

設計（DESIGN.md §6）:
- 即時 200 OK を返し、重い処理は BackgroundTasks に流す（Phase 1 は Reply Message
  で完結するため Cloud Tasks までは行かない）
- 署名検証失敗で 401
- LINE_* env 未設定で 503
- 個別イベントの失敗は握りつぶしてログのみ（LINE の再送を抑止するため常に 200）
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status
from linebot.v3.webhooks import (
    FollowEvent,
    MessageEvent,
    TextMessageContent,
    UnfollowEvent,
)
from linebot.v3.webhooks.models import Event

from app.config import settings
from app.handlers.command_router import CommandRouter, HandlerDeps
from app.handlers.disclaimer import BLOCKED_DELETION_NOTE, FOLLOW_GREETING
from app.models import UserStatus
from app.repositories import (
    InMemoryRepoBundle,
    QuestionPool,
    load_question_pool,
)
from app.services.line_client import (
    InvalidSignatureError,
    LineBotClient,
    get_line_bot_client,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["line"])


# ---- DI シングルトン（テストで差し替え可） ----

_repo_bundle: InMemoryRepoBundle | None = None
_question_pool: QuestionPool | None = None


def get_repo_bundle() -> InMemoryRepoBundle:
    global _repo_bundle
    if _repo_bundle is None:
        _repo_bundle = InMemoryRepoBundle()
    return _repo_bundle


def set_repo_bundle(bundle: InMemoryRepoBundle | None) -> None:
    global _repo_bundle
    _repo_bundle = bundle


def get_question_pool() -> QuestionPool:
    global _question_pool
    if _question_pool is None:
        _question_pool = load_question_pool(settings.seed_questions_path)
    return _question_pool


def set_question_pool(pool: QuestionPool | None) -> None:
    global _question_pool
    _question_pool = pool


def _build_deps() -> HandlerDeps:
    bundle = get_repo_bundle()
    return HandlerDeps(
        users=bundle.users,
        line_user_index=bundle.line_user_index,
        sessions=bundle.sessions,
        answer_histories=bundle.answer_histories,
        pool=get_question_pool(),
    )


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


# ---- ルート本体 ----


@router.post("/webhook")
async def webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_line_signature: str = Header(default=""),
) -> dict[str, str]:
    client = _require_line_client()
    body = await request.body()
    try:
        events = client.parse_events(body, x_line_signature)
    except InvalidSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid signature"
        ) from exc

    deps = _build_deps()
    bot_channel_id = settings.line_channel_id

    for event in events:
        background_tasks.add_task(
            _process_event_safely, client, deps, event, bot_channel_id
        )

    return {"status": "accepted"}


async def _process_event_safely(
    client: LineBotClient,
    deps: HandlerDeps,
    event: Event,
    bot_channel_id: str,
) -> None:
    """個別イベント処理の例外を握り潰す（LINE の再送を抑止するため）。

    LINE 公式仕様: Webhook が 5xx を返すと LINE は再送を試みるため、ハンドラ単位の
    一時的失敗で再送ループに入らないよう、ここで例外を捕捉してログだけ残す。
    署名検証はこの関数の手前 `webhook` で済んでいるため、安全側に倒している。
    """
    try:
        await _process_event(client, deps, event, bot_channel_id)
    except Exception:  # noqa: BLE001
        logger.exception("LINE event handling failed")


async def _process_event(
    client: LineBotClient,
    deps: HandlerDeps,
    event: Event,
    bot_channel_id: str,
) -> None:
    if isinstance(event, FollowEvent):
        line_user_id = _extract_user_id(event)
        if line_user_id:
            await deps.identity.get_or_create(
                line_user_id, bot_channel_id=bot_channel_id
            )
        if event.reply_token:
            client.reply_text(event.reply_token, [FOLLOW_GREETING])
        return

    if isinstance(event, UnfollowEvent):
        line_user_id = _extract_user_id(event)
        if not line_user_id:
            return
        internal_uid = await deps.line_user_index.get_internal_uid(line_user_id)
        if internal_uid is None:
            return
        user = await deps.users.get(internal_uid)
        if user is None:
            return
        scheduled_at = datetime.now(UTC) + timedelta(days=30)
        blocked = user.model_copy(
            update={
                "status": UserStatus.BLOCKED,
                "scheduled_deletion_at": scheduled_at,
            }
        )
        await deps.users.upsert(blocked)
        logger.info(
            "user blocked: internal_uid=%s scheduled_deletion_at=%s. note=%s",
            internal_uid,
            scheduled_at.isoformat(),
            BLOCKED_DELETION_NOTE,
        )
        return

    if isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent):
        line_user_id = _extract_user_id(event)
        if not line_user_id:
            return
        replies = await CommandRouter(deps).dispatch_text(
            line_user_id=line_user_id,
            text=event.message.text,
            bot_channel_id=bot_channel_id,
        )
        if event.reply_token and replies:
            client.reply_text(event.reply_token, replies)
        return

    logger.debug("unsupported event type: %s", type(event).__name__)


def _extract_user_id(event: Event) -> str | None:
    src = getattr(event, "source", None)
    if src is None:
        return None
    return getattr(src, "user_id", None)
