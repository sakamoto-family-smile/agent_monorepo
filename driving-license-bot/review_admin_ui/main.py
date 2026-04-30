"""review-admin-ui FastAPI エントリポイント。

C1: スケルトン (/healthz, / の認可)
C2: ReviewService と接続、queue / detail / approve / reject API
C3: 本番 wiring (pgvector + Firestore) + lifespan で接続プール管理
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.instrumentation.events import (
    EVENT_HUMAN_REVIEW_DECIDED,
    EVENT_QUESTION_PUBLISHED,
    emit_business_event,
)
from review_admin_ui.auth import (
    SESSION_USER_KEY,
    AdminUser,
    install_redirect_handler,
    is_email_allowed,
    require_admin,
)
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
_PGVECTOR_POOL_KEY = "_pgvector_pool"


async def _build_default_review_service(app: FastAPI) -> ReviewService:
    """env から実 service を構築。

    QUESTION_BANK_BACKEND=pgvector + REPOSITORY_BACKEND=firestore を本番想定。
    pool は lifespan で close 出来るよう app.state に保持。

    テストや dev では create_app(review_service=...) で先に注入されるので
    本関数は呼ばれない。
    """
    from app.config import settings as app_settings

    backend = app_settings.question_bank_backend.lower()

    # ---- bank ----
    if backend == "pgvector":
        from app.repositories.question_bank.pgvector_impl import (
            PgvectorQuestionBank,
            build_pgvector_pool,
        )

        pool = await build_pgvector_pool(
            host=app_settings.cloudsql_host,
            port=app_settings.cloudsql_port,
            user=app_settings.cloudsql_user,
            password=app_settings.cloudsql_password,
            database=app_settings.cloudsql_db,
            min_size=1,
            max_size=3,
        )
        setattr(app.state, _PGVECTOR_POOL_KEY, pool)
        bank = PgvectorQuestionBank(pool)
        logger.info("review-admin-ui: PgvectorQuestionBank wired")
    else:
        from app.repositories.question_bank import InMemoryQuestionBank

        bank = InMemoryQuestionBank()
        logger.info("review-admin-ui: InMemoryQuestionBank (dev/test)")

    # ---- repo (本文) ----
    repo_backend = app_settings.repository_backend.lower()
    if repo_backend == "firestore":
        from google.cloud.firestore_v1 import AsyncClient

        from app.repositories.firestore_repos import FirestoreQuestionRepo

        client = AsyncClient(project=app_settings.google_cloud_project)
        repo = FirestoreQuestionRepo(client)
        logger.info("review-admin-ui: FirestoreQuestionRepo wired")
    else:
        from app.repositories.question_repo import InMemoryQuestionRepo

        repo = InMemoryQuestionRepo()
        logger.info("review-admin-ui: InMemoryQuestionRepo (dev/test)")

    return ReviewService(bank=bank, repo=repo)


async def get_review_service(request: Request) -> ReviewService:
    svc = getattr(request.app.state, _REVIEW_SERVICE_KEY, None)
    if svc is None:
        svc = await _build_default_review_service(request.app)
        setattr(request.app.state, _REVIEW_SERVICE_KEY, svc)
    return svc


@asynccontextmanager
async def _lifespan(app: FastAPI):
    yield
    # cleanup pgvector pool（生存していれば）
    pool = getattr(app.state, _PGVECTOR_POOL_KEY, None)
    if pool is not None:
        try:
            await pool.close()
            logger.info("review-admin-ui: pgvector pool closed")
        except Exception:  # noqa: BLE001
            logger.exception("review-admin-ui: pool close failed")


def _build_oauth_client():
    """Authlib OAuth client (Google) を構築。dev_bypass 時は None を返す。"""
    if settings.dev_bypass:
        return None
    if not (settings.oauth_client_id and settings.oauth_client_secret):
        # 本番想定だが env 未設定: middleware は load するがログイン時にエラー
        logger.warning("ADMIN_OAUTH_CLIENT_ID / SECRET 未設定 — /login で 500 になる")
        return None
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=settings.oauth_client_id,
        client_secret=settings.oauth_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    return oauth


def create_app(review_service: ReviewService | None = None) -> FastAPI:
    app = FastAPI(
        title="driving-license-bot review admin UI",
        version=settings.service_version,
        lifespan=_lifespan,
    )
    if review_service is not None:
        setattr(app.state, _REVIEW_SERVICE_KEY, review_service)

    # Session cookie. dev_bypass 時もテストで使うため必ず install。
    # https_only は Cloud Run で True、ローカルテストでは settings.env=='local'
    # でも cookie は送られる（host='testclient' なら secure flag は無視）。
    session_secret = settings.session_secret_key or "dev-only-insecure-secret-do-not-use"
    app.add_middleware(
        SessionMiddleware,
        secret_key=session_secret,
        max_age=settings.session_max_age_seconds,
        same_site="lax",
        https_only=(settings.env != "local"),
    )

    install_redirect_handler(app)
    oauth_client = _build_oauth_client()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {
            "status": "ok",
            "service": settings.service_name,
            "version": settings.service_version,
        }

    @app.get("/login")
    async def login(request: Request) -> RedirectResponse:
        """Google OAuth consent screen にリダイレクト。"""
        if settings.dev_bypass:
            # dev: 既にログイン済みとみなして redirect
            return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        if oauth_client is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="OAuth client is not configured",
            )
        redirect_uri = settings.oauth_redirect_url or str(request.url_for("auth_callback"))
        return await oauth_client.google.authorize_redirect(request, redirect_uri)

    @app.get("/auth/callback", name="auth_callback")
    async def auth_callback(request: Request):
        """Google からの redirect を受け、ID token 検証 → session に email 保存。"""
        if oauth_client is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="OAuth client is not configured",
            )
        try:
            token = await oauth_client.google.authorize_access_token(request)
        except Exception as exc:  # noqa: BLE001 — OAuth flow 失敗は多岐
            logger.warning("OAuth callback failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="OAuth authorization failed",
            ) from exc

        userinfo = token.get("userinfo") or {}
        email = userinfo.get("email", "")
        email_verified = userinfo.get("email_verified", False)
        if not email or not email_verified:
            logger.warning("OAuth callback: email missing or unverified (%s)", email)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="email not verified",
            )

        if not is_email_allowed(email):
            logger.info("denied: %s not in allowlist", email)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="email not allowed",
            )

        request.session[SESSION_USER_KEY] = email
        logger.info("login ok: %s", email)
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    @app.get("/logout")
    async def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="question not found")
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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="question not found")
        emit_business_event(
            event_name=EVENT_QUESTION_PUBLISHED,
            properties={
                "question_id": question_id,
                "decided_by": user.email,
                "via": "review_admin_ui",
            },
        )
        logger.info("approve question_id=%s by=%s", question_id, user.email)
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/questions/{question_id}/reject")
    async def reject(
        question_id: str,
        request: Request,
        user: AdminUser = Depends(require_admin),
        svc: ReviewService = Depends(get_review_service),
    ) -> RedirectResponse:
        # form / query どちらでも reason_tag を受ける（最小実装）
        form = (
            await request.form()
            if request.headers.get("content-type", "").startswith(
                "application/x-www-form-urlencoded"
            )
            else {}
        )
        reason_tag = (
            form.get("reason_tag") if form else request.query_params.get("reason_tag")
        ) or "unspecified"

        ok = await svc.reject(question_id)
        if not ok:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="question not found")
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
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

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
