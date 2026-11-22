"""golf-notes-agent の backend (PROPOSAL-0016)。

    uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8080

起動時に golf.db を最新のスキーマにし、同じプロセスの中でジョブのワーカーと定期処理 (バックアップ・死活監視) を動かす
(golf.db に書くのはこのプロセスだけ)。
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import sqlalchemy as sa
from fastapi import FastAPI, Request

from app import webhook
from app.config import Settings
from app.deps import Deps
from app.jobs import media as media_job
from app.jobs.worker import Worker
from app.line.api import HttpLineApi, LineApi
from app.scheduler import Scheduler
from app.storage import db
from app.timeutil import Clock, utcnow

logger = logging.getLogger(__name__)


def build_worker(deps: Deps) -> Worker:
    return Worker(deps=deps, kinds={media_job.KIND: media_job.JOB})


async def open_deps(settings: Settings, line: LineApi | None = None, clock: Clock = utcnow) -> Deps:
    settings.paths.ensure()
    await asyncio.to_thread(db.upgrade, settings.paths.db)
    if not settings.allowed_user_ids:
        logger.warning("ALLOWED_USER_IDS が空なので、どのメッセージも保存しません")
    engine = db.make_engine(settings.paths.db)
    api = line or HttpLineApi(settings.line_channel_access_token)
    return Deps(settings=settings, engine=engine, line=api, clock=clock)


async def close_deps(deps: Deps) -> None:
    if isinstance(deps.line, HttpLineApi):
        await deps.line.close()
    await deps.engine.dispose()


def create_app(
    settings: Settings | None = None,
    line: LineApi | None = None,
    clock: Clock = utcnow,
) -> FastAPI:
    settings = settings or Settings.from_env()
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        deps = await open_deps(settings, line, clock)
        app.state.deps = deps
        stop = asyncio.Event()
        tasks = [
            asyncio.create_task(build_worker(deps).run_forever(stop)),
            asyncio.create_task(Scheduler(deps).run_forever(stop)),
        ]
        try:
            yield
        finally:
            stop.set()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task
            await close_deps(deps)

    # 本番では docs・OpenAPI を出さない (Funnel で公開するのは /api/line 配下だけだが念のため)
    docs = None if settings.is_prod else "/docs"
    app = FastAPI(
        title="golf-notes-agent",
        lifespan=lifespan,
        docs_url=docs,
        redoc_url=None,
        openapi_url=None if settings.is_prod else "/openapi.json",
    )
    app.include_router(webhook.router)

    @app.get("/healthz")
    async def healthz(request: Request) -> dict[str, bool]:
        deps: Deps = request.app.state.deps
        async with deps.engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
        return {"ok": True}

    return app
