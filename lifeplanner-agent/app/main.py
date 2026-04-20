import logging
from contextlib import asynccontextmanager
from pathlib import Path

from config import settings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from services.database import close_db, init_db, init_engine

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)


def _ensure_data_dirs() -> None:
    for dir_path in (settings.data_dir, settings.mf_csv_dir):
        Path(dir_path).mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ensure_data_dirs()
    init_engine()
    # ローカル開発では SQLAlchemy metadata から直接テーブルを作成する。
    # 本番 (Postgres) では Alembic migration を使う想定のため、非 local では作成しない。
    if settings.app_env == "local":
        await init_db()
    logger.info("Lifeplanner Agent started (env=%s)", settings.app_env)
    try:
        yield
    finally:
        await close_db()


app = FastAPI(
    title="ライフプランナーエージェント API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Household-ID"],
)

from routes.anomalies import router as anomalies_router  # noqa: E402
from routes.chat import router as chat_router  # noqa: E402
from routes.line import router as line_router  # noqa: E402
from routes.line_liff import (  # noqa: E402
    liff_api_router,
    liff_page_router,
)
from routes.networth import router as networth_router  # noqa: E402
from routes.profile import router as profile_router  # noqa: E402
from routes.scenarios import router as scenarios_router  # noqa: E402
from routes.simulate import router as simulate_router  # noqa: E402
from routes.summary import router as summary_router  # noqa: E402
from routes.transactions import router as transactions_router  # noqa: E402
from routes.upload import router as upload_router  # noqa: E402

app.include_router(upload_router)
app.include_router(transactions_router)
app.include_router(summary_router)
app.include_router(networth_router)
app.include_router(anomalies_router)
app.include_router(profile_router)
app.include_router(scenarios_router)
app.include_router(simulate_router)
app.include_router(chat_router)
app.include_router(line_router)
app.include_router(liff_page_router)
app.include_router(liff_api_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "lifeplanner-agent"}
