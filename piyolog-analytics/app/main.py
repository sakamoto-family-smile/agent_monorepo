"""piyolog-analytics FastAPI エントリポイント。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from config import settings
from fastapi import FastAPI
from instrumentation import setup_observability, shutdown_observability
from routes.health import router as health_router
from routes.line import get_repo
from routes.line import router as line_router

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_observability()
    # SQLite スキーマを初期化 (初回のみ DDL 流し込み)
    repo = get_repo()
    await repo.initialize()
    logger.info(
        "piyolog-analytics started (env=%s, family_id=%s)",
        settings.app_env,
        settings.family_id,
    )
    try:
        yield
    finally:
        await shutdown_observability()


def create_app() -> FastAPI:
    app = FastAPI(
        title="piyolog-analytics",
        version=settings.service_version,
        lifespan=lifespan,
    )
    app.include_router(health_router)
    app.include_router(line_router, prefix="/api")
    return app


app = create_app()
