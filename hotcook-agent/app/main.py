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
    """Create required data directories at startup."""
    for dir_path in [
        Path(settings.data_dir),
        Path(settings.db_path).parent,
        Path(settings.analytics_data_dir),
    ]:
        dir_path.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ensure_data_dirs()
    await init_db()
    setup_observability()
    logger.info("Hotcook Agent started (env=%s)", settings.app_env)
    try:
        yield
    finally:
        await shutdown_observability()


app = FastAPI(
    title="ホットクック対応エージェント API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

from routes.inventory import router as inventory_router
from routes.recipes import router as recipes_router

app.include_router(recipes_router, prefix="/api")
app.include_router(inventory_router, prefix="/api")


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "hotcook-agent"}
