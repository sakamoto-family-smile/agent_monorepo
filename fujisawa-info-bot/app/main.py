"""fujisawa-info-bot FastAPI entrypoint (Phase 0 雛形)。

Phase 0 では `/health` endpoint のみを提供し、 Cloud Run startup probe と
CI 上の smoke test の両方で利用する。 LINE webhook / Pub/Sub handler 等は
Phase 1 以降で追加する (proposal 0004 §4.3 参照)。
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="fujisawa-info-bot",
    description="藤沢市公式 HP を一次ソースとする LINE Bot エージェント (Phase 0 雛形)",
    version="0.1.0",
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Cloud Run startup probe + 監視用の最小 endpoint。"""
    return {"status": "ok"}
