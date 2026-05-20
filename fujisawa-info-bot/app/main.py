"""fujisawa-info-bot FastAPI entrypoint。

Phase 2 で以下を提供:
- `GET /health`: Cloud Run startup probe + CI 上の smoke
- `POST /webhook`: LINE Messaging API のコールバック (`app.routes.line`)

startup で LangGraph + LLM + KnowledgeStore を初期化し、 `app.state.graph_deps`
として route から参照する。 shutdown で pgvector pool を close する。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.graph import GraphDependencies
from app.kb import build_knowledge_backend
from app.llm import build_llm_client
from app.routes import line as line_routes

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """LLM / KB の初期化を 1 回だけ実行する。

    pgvector pool は shutdown 時に close する。
    """
    logger.info(
        "fujisawa-info-bot startup: llm=%s kb=%s embedding=%s",
        settings.llm_provider,
        settings.kb_store_mode,
        settings.embedding_provider,
    )
    llm = build_llm_client(settings)
    backend = await build_knowledge_backend(settings)
    app.state.graph_deps = GraphDependencies(
        llm=llm,
        embedding=backend.embedding,
        store=backend.store,
        top_k=settings.rag_top_k,
    )
    app.state.kb_pool = backend.pool
    try:
        yield
    finally:
        pool = getattr(app.state, "kb_pool", None)
        if pool is not None and hasattr(pool, "close"):
            await pool.close()


app = FastAPI(
    title="fujisawa-info-bot",
    description="藤沢市公式 HP を一次ソースとする LINE Bot エージェント",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(line_routes.router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Cloud Run startup probe + 監視用の最小 endpoint。"""
    return {"status": "ok"}
