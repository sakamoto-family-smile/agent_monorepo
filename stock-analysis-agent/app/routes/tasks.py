"""Cloud Tasks worker エンドポイント (PROPOSAL-0011 P3-A)。

`POST /api/tasks/analyze` — Cloud Tasks から OIDC 認証付きで叩かれ、分析本体を
同期実行して LINE Push する。webhook (stock-analysis-line) は enqueue するだけ。

認証:
- worker は非公開 Cloud Run (invoker は Cloud Tasks の invoker SA のみ)。Cloud Run が
  OIDC token の署名・audience を検証したうえで、app でも email=invoker SA を確認する。
- `TASKS_INVOKER_SA` 未設定時に検証を skip するのはローカル開発 (APP_ENV=local) のみ。
  それ以外の環境で未設定なら設定漏れとして 503 で拒否する (fail-closed)。

リトライ:
- 分析失敗時は Cloud Tasks の `X-CloudTasks-TaskRetryCount` を見て、上限未満なら
  500 を返して再試行させる。上限到達時はユーザにエラー通知して 200 (ack)。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, Request, status

from analytics_platform.observability.context import set_current_user_id
from config import settings
from services.line_client import get_line_bot_client
from services.task_queue import worker_audience
from services.line_handler import (
    HandlerDeps,
    push_analysis_failure,
    run_and_deliver_analysis,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _verify_oidc(authorization: str | None) -> None:
    """Cloud Tasks の OIDC token を検証する。invoker SA 未設定ならローカルのみ skip。"""
    if not settings.tasks_invoker_sa:
        if settings.app_env == "local":
            return
        logger.error("TASKS_INVOKER_SA 未設定のため worker タスクを拒否します")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="worker auth not configured"
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        from google.auth.transport import requests as grequests  # noqa: PLC0415
        from google.oauth2 import id_token  # noqa: PLC0415

        audience = worker_audience(settings.tasks_worker_url) if settings.tasks_worker_url else None
        claims = id_token.verify_oauth2_token(token, grequests.Request(), audience=audience)
    except Exception as e:
        logger.warning("OIDC verify failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid OIDC token"
        ) from e
    if claims.get("email") != settings.tasks_invoker_sa:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="unexpected token principal"
        )


@router.post("/analyze")
async def analyze_task(
    request: Request,
    authorization: str | None = Header(default=None),
    x_cloudtasks_taskretrycount: int = Header(default=0, alias="X-CloudTasks-TaskRetryCount"),
) -> dict[str, str]:
    _verify_oidc(authorization)

    payload = await request.json()
    user_id = (payload or {}).get("user_id")
    target = (payload or {}).get("target")
    if not user_id or not target:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="user_id and target required"
        )

    line_client = get_line_bot_client()
    if line_client is None:
        # LINE 未設定では push できない → リトライしても無駄なので 200 で握る。
        logger.error("LINE client not configured on worker; dropping task")
        return {"status": "skipped_no_line_client"}

    deps = HandlerDeps(line_client=line_client, schedule_background=lambda f: None)

    # ユーザー別利用統計: orchestrator 内の全イベント (llm_call / business 等) に付与
    set_current_user_id(user_id)

    try:
        await run_and_deliver_analysis(deps, to=user_id, target=target)
        return {"status": "ok"}
    except Exception as e:
        attempt = x_cloudtasks_taskretrycount + 1  # 1-based
        if attempt < settings.tasks_max_attempts:
            # まだ余地あり → 500 で Cloud Tasks にリトライさせる (ユーザ通知はしない)
            logger.warning(
                "analyze task failed (attempt %d/%d), will retry: %s",
                attempt, settings.tasks_max_attempts, e,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="retry"
            ) from e
        # 試行上限 → ユーザにエラー通知して ack
        logger.exception("analyze task exhausted retries for target=%s", target)
        await push_analysis_failure(deps, to=user_id, target=target, reason=str(e))
        return {"status": "failed_notified"}
