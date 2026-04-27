"""driving-license-bot FastAPI エントリポイント。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.routes.health import router as health_router
from app.routes.line import router as line_router

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "driving-license-bot started service=%s version=%s env=%s line_configured=%s",
        settings.service_name,
        settings.service_version,
        settings.env,
        settings.line_configured,
    )
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="driving-license-bot",
        version=settings.service_version,
        lifespan=lifespan,
    )
    app.include_router(health_router)
    app.include_router(line_router)
    return app


app = create_app()
