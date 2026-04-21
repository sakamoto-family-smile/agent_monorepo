import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from instrumentation import setup_observability, shutdown_observability
from services.database import init_db

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)


def _ensure_data_dirs() -> None:
    """Create required data directories."""
    for dir_path in [
        settings.data_dir,
        settings.charts_dir,
        settings.reports_dir,
        settings.cache_dir,
        settings.dictionaries_dir,
    ]:
        Path(dir_path).mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ensure_data_dirs()
    await init_db()
    setup_observability()
    logger.info("Stock Analysis Agent started (env=%s)", settings.app_env)
    try:
        yield
    finally:
        await shutdown_observability()


app = FastAPI(
    title="株価分析エージェント API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

from routes.analysis import router as analysis_router
from routes.reports import router as reports_router
from routes.screener import router as screener_router

app.include_router(analysis_router, prefix="/api")
app.include_router(reports_router, prefix="/api")
app.include_router(screener_router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "stock-analysis-agent"}
