"""tech-news-agent FastAPI エントリポイント。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from instrumentation import setup_observability, shutdown_observability
from routes.health import router as health_router
from routes.pipeline import get_dedup_repo
from routes.pipeline import router as pipeline_router

from config import settings

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_observability()
    repo = get_dedup_repo()
    await repo.initialize()
    logger.info(
        "tech-news-agent started (env=%s, service=%s)",
        settings.app_env,
        settings.analytics_service_name,
    )
    try:
        yield
    finally:
        await shutdown_observability()


def create_app() -> FastAPI:
    app = FastAPI(
        title="tech-news-agent",
        version=settings.service_version,
        lifespan=lifespan,
    )
    app.include_router(health_router)
    app.include_router(pipeline_router)
    return app


app = create_app()
