"""couple-roster-bot FastAPI entrypoint。

- `GET  /health`       : Cloud Run startup probe + CI smoke
- `POST /webhook`      : LINE Messaging API コールバック（`app.routes.line`）
- `GET  /liff` ほか    : LIFF フォーム + JSON API（`app.routes.liff`）

startup で `AppDeps`（RosterService / OCR エンジン / 保留インポート）を 1 度だけ
構築し、`app.state.deps` として route から参照する。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.deps import AppDeps
from app.routes import liff as liff_routes
from app.routes import line as line_routes

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """依存の初期化を 1 回だけ実行する。"""
    logger.info(
        "couple-roster-bot startup: storage=%s ocr=%s",
        settings.storage_mode,
        settings.ocr_provider,
    )
    app.state.deps = AppDeps.from_settings(settings)
    yield


app = FastAPI(
    title="couple-roster-bot",
    description="夫婦で使う名簿管理システム（LINE × スプレッドシート）",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(line_routes.router)
app.include_router(liff_routes.router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Cloud Run startup probe + 監視用の最小 endpoint。"""
    return {"status": "ok"}
