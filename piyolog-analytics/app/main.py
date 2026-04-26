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
    repo = get_repo()
    if settings.db_auto_create:
        # dev/test (SQLite) は create_all で初期化。本番 Postgres は alembic を使うため
        # `DB_AUTO_CREATE=false` にして起動時 DDL を打たない。
        await repo.initialize()
    logger.info(
        "piyolog-analytics started (env=%s, family_id=%s, db=%s)",
        settings.app_env,
        settings.family_id,
        repo.dialect,
    )
    try:
        yield
    finally:
        await shutdown_observability()
        await repo.dispose()


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
