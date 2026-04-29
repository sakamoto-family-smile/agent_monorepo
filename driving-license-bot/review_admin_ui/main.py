"""review-admin-ui FastAPI エントリポイント（Phase 2-C1 スケルトン）。

C1 範囲:
- /healthz  健康チェック (認可不要)
- /        空のレビュー一覧ページ (認可必須、IAP JWT or dev bypass)

C2 で追加予定:
- /queue?status=needs_review
- POST /questions/{id}/approve|reject|edit
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from review_admin_ui.auth import AdminUser, require_admin
from review_admin_ui.config import settings

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))


def create_app() -> FastAPI:
    app = FastAPI(
        title="driving-license-bot review admin UI",
        version=settings.service_version,
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {
            "status": "ok",
            "service": settings.service_name,
            "version": settings.service_version,
        }

    @app.get("/", response_class=HTMLResponse)
    async def index(
        request: Request,
        user: AdminUser = Depends(require_admin),
    ) -> HTMLResponse:
        # C2 でここに question_bank からの一覧 fetch を入れる
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "user_email": user.email,
                "service_name": settings.service_name,
                "questions": [],  # C2 で実データに差し替え
            },
        )

    return app


app = create_app()
