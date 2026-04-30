"""driving-license-bot FastAPI エントリポイント。"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.instrumentation import setup_observability, shutdown_observability
from app.repositories import BankBackedQuestionPool
from app.routes.health import router as health_router
from app.routes.line import (
    get_question_pool,
    set_pgvector_pool,
)
from app.routes.line import (
    router as line_router,
)

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


async def _periodic_refresh(pool: BankBackedQuestionPool, interval: int) -> None:
    """N 秒ごとに bank プールの cache を refresh する background task。"""
    while True:
        await asyncio.sleep(interval)
        try:
            count = await pool.refresh()
            logger.info("[pool refresh] cached=%d", count)
        except Exception:  # noqa: BLE001 — 運用継続を優先、ログだけ残す
            logger.exception("[pool refresh] failed (will retry next cycle)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_observability()
    logger.info(
        "driving-license-bot started service=%s version=%s env=%s "
        "line_configured=%s repository_backend=%s analytics_enabled=%s "
        "question_pool_source=%s",
        settings.service_name,
        settings.service_version,
        settings.env,
        settings.line_configured,
        settings.repository_backend,
        settings.analytics_enabled,
        settings.question_pool_source,
    )

    # Phase 2-X1: bank プール用 pgvector pool を起動時に build
    pgvector_pool = None
    refresh_task: asyncio.Task | None = None
    if (
        settings.question_pool_source.lower() == "bank"
        and settings.question_bank_backend.lower() == "pgvector"
    ):
        from app.repositories.question_bank.pgvector_impl import (
            build_pgvector_pool,
        )

        pgvector_pool = await build_pgvector_pool(
            host=settings.cloudsql_host,
            port=settings.cloudsql_port,
            user=settings.cloudsql_user,
            password=settings.cloudsql_password,
            database=settings.cloudsql_db,
            min_size=1,
            max_size=3,
        )
        set_pgvector_pool(pgvector_pool)
        logger.info("pgvector pool initialized (line-bot)")

    # bank プール初回 refresh + 定期 refresh task 起動
    if settings.question_pool_source.lower() == "bank":
        pool = get_question_pool()
        if isinstance(pool, BankBackedQuestionPool):
            count = await pool.refresh()
            logger.info("bank pool initial refresh: cached=%d", count)
            interval = settings.question_pool_refresh_interval_seconds
            if interval > 0:
                refresh_task = asyncio.create_task(
                    _periodic_refresh(pool, interval)
                )

    try:
        yield
    finally:
        if refresh_task is not None:
            refresh_task.cancel()
            try:
                await refresh_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if pgvector_pool is not None:
            try:
                await pgvector_pool.close()
                logger.info("pgvector pool closed")
            except Exception:  # noqa: BLE001
                logger.exception("pgvector pool close failed")
        await shutdown_observability()


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
