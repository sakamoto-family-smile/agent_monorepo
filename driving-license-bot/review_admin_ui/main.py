"""review-admin-ui FastAPI エントリポイント。

C1: スケルトン (/healthz, / の認可)
C2: ReviewService と接続、queue / detail / approve / reject API
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.instrumentation.events import (
    EVENT_HUMAN_REVIEW_DECIDED,
    EVENT_QUESTION_PUBLISHED,
    emit_business_event,
)
from review_admin_ui.auth import AdminUser, require_admin
from review_admin_ui.config import settings
from review_admin_ui.services import (
    STATUS_NEEDS_REVIEW,
    STATUS_PUBLISHED,
    STATUS_REJECTED,
    ReviewService,
)

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))

# ReviewService は app.state にぶら下げて DI する（テストで差し替え可能）
_REVIEW_SERVICE_KEY = "review_service"


def _build_default_review_service() -> ReviewService:
    """env から実 service を構築（本番: pgvector + Firestore）。

    テストや dev では create_app() 呼び出し前に app.state に直接セットすれば
    本関数は呼ばれない。
    """
    from app.config import settings as app_settings
    from app.repositories.question_bank import InMemoryQuestionBank
    from app.repositories.question_repo import InMemoryQuestionRepo

    backend = app_settings.question_bank_backend.lower()
    if backend != "pgvector":
        logger.info("review-admin-ui: using InMemory bank/repo (dev/test)")
        return ReviewService(
            bank=InMemoryQuestionBank(), repo=InMemoryQuestionRepo()
        )

    # 本番: pgvector + Firestore
    raise RuntimeError(
        "review-admin-ui: production wiring (pgvector + Firestore) not implemented "
        "yet — set ReviewService manually via app.state.review_service or use "
        "QUESTION_BANK_BACKEND=memory for now"
    )


def get_review_service(request: Request) -> ReviewService:
    svc = getattr(request.app.state, _REVIEW_SERVICE_KEY, None)
    if svc is None:
        svc = _build_default_review_service()
        setattr(request.app.state, _REVIEW_SERVICE_KEY, svc)
    return svc


def create_app(review_service: ReviewService | None = None) -> FastAPI:
    app = FastAPI(
        title="driving-license-bot review admin UI",
        version=settings.service_version,
    )
    if review_service is not None:
        setattr(app.state, _REVIEW_SERVICE_KEY, review_service)

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
        svc: ReviewService = Depends(get_review_service),
    ) -> HTMLResponse:
        items = await svc.list_queue(status=STATUS_NEEDS_REVIEW)
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "user_email": user.email,
                "service_name": settings.service_name,
                "items": items,
                "status": STATUS_NEEDS_REVIEW,
            },
        )

    @app.get("/questions/{question_id}", response_class=HTMLResponse)
    async def detail(
        question_id: str,
        request: Request,
        user: AdminUser = Depends(require_admin),
        svc: ReviewService = Depends(get_review_service),
    ) -> HTMLResponse:
        item = await svc.get_detail(question_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="question not found"
            )
        return templates.TemplateResponse(
            request,
            "detail.html",
            {
                "user_email": user.email,
                "service_name": settings.service_name,
                "item": item,
            },
        )

    @app.post("/questions/{question_id}/approve")
    async def approve(
        question_id: str,
        user: AdminUser = Depends(require_admin),
        svc: ReviewService = Depends(get_review_service),
    ) -> RedirectResponse:
        ok = await svc.approve(question_id)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="question not found"
            )
        emit_business_event(
            event_name=EVENT_QUESTION_PUBLISHED,
            properties={
                "question_id": question_id,
                "decided_by": user.email,
                "via": "review_admin_ui",
            },
        )
        logger.info("approve question_id=%s by=%s", question_id, user.email)
        return RedirectResponse(
            url="/", status_code=status.HTTP_303_SEE_OTHER
        )

    @app.post("/questions/{question_id}/reject")
    async def reject(
        question_id: str,
        request: Request,
        user: AdminUser = Depends(require_admin),
        svc: ReviewService = Depends(get_review_service),
    ) -> RedirectResponse:
        # form / query どちらでも reason_tag を受ける（最小実装）
        form = await request.form() if request.headers.get("content-type", "").startswith(
            "application/x-www-form-urlencoded"
        ) else {}
        reason_tag = (
            form.get("reason_tag") if form else request.query_params.get("reason_tag")
        ) or "unspecified"

        ok = await svc.reject(question_id)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="question not found"
            )
        emit_business_event(
            event_name=EVENT_HUMAN_REVIEW_DECIDED,
            properties={
                "question_id": question_id,
                "verdict": STATUS_REJECTED,
                "reason_tag": reason_tag,
                "decided_by": user.email,
                "via": "review_admin_ui",
            },
        )
        logger.info(
            "reject question_id=%s reason=%s by=%s",
            question_id,
            reason_tag,
            user.email,
        )
        return RedirectResponse(
            url="/", status_code=status.HTTP_303_SEE_OTHER
        )

    @app.get("/published", response_class=HTMLResponse)
    async def published_list(
        request: Request,
        user: AdminUser = Depends(require_admin),
        svc: ReviewService = Depends(get_review_service),
    ) -> HTMLResponse:
        """approve 済み一覧（運営者の確認用）。"""
        items = await svc.list_queue(status=STATUS_PUBLISHED)
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "user_email": user.email,
                "service_name": settings.service_name,
                "items": items,
                "status": STATUS_PUBLISHED,
            },
        )

    return app


app = create_app()
