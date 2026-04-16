import asyncio
import json
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from models.stock import AnalysisRequest
from agents.orchestrator import run_analysis

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/analyze")
async def analyze_stock(request: AnalysisRequest):
    """Run stock analysis and stream results."""
    async def event_stream():
        try:
            async for event in run_analysis(request):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except TimeoutError as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        except Exception as e:
            logger.exception("Analysis error: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'message': '分析中にエラーが発生しました'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.post("/resolve-ticker")
async def resolve_ticker_endpoint(body: dict):
    """Resolve company name to ticker."""
    from agents.ticker_resolver import resolve_ticker
    query = body.get("query", "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    result = await resolve_ticker(query)
    return result.model_dump()
