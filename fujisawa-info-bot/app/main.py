"""fujisawa-info-bot FastAPI entrypoint。

Phase 1 までで以下を提供:
- `GET /health`: Cloud Run startup probe + CI 上の smoke
- `POST /webhook`: LINE Messaging API のコールバック (`app.routes.line` に実装)

Phase 2+ で LangGraph Supervisor 経由のメッセージ処理に置き換わるが、 endpoint
そのものは本ファイルで配線する。
"""

from __future__ import annotations

from fastapi import FastAPI

from app.routes import line as line_routes

app = FastAPI(
    title="fujisawa-info-bot",
    description="藤沢市公式 HP を一次ソースとする LINE Bot エージェント",
    version="0.1.0",
)
app.include_router(line_routes.router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Cloud Run startup probe + 監視用の最小 endpoint。"""
    return {"status": "ok"}
