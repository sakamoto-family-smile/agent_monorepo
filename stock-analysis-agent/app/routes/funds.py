"""投資信託 (ETF プロキシ) のオススメランキング API。"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict

from fastapi import APIRouter

from agents.fund_screener import run_fund_recommend
from analytics_platform.observability.hashing import sha256_prefixed
from config import settings
from instrumentation import get_analytics_logger
from models.stock import FundRecommendRequest, FundRecommendResult

logger = logging.getLogger(__name__)
router = APIRouter()


def _build_business_attributes(
    req: FundRecommendRequest, result: FundRecommendResult
) -> Dict[str, Any]:
    return {
        "category": req.category,
        "horizon": req.horizon,
        "top_n": req.top_n,
        "require_uptrend": req.require_uptrend,
        "total_scanned": result.total_scanned,
        "candidates_returned": len(result.candidates),
        "top_tickers": [c.ticker for c in result.candidates],
    }


@router.post("/funds/recommend", response_model=FundRecommendResult)
async def recommend_funds(request: FundRecommendRequest) -> FundRecommendResult:
    """投資信託 (ETF プロキシ) のオススメ銘柄をランキング形式で返す。

    - category: us_index / global / dividend / sector / all
    - horizon: 3mo / 6mo / 1y / 3y (トレンド評価期間)
    - top_n: 上位何件返すか (最大20)
    - require_uptrend: SMA50 > SMA200 を必須化するか
    """
    al = get_analytics_logger()
    session_id = f"fund_recommend_{uuid.uuid4().hex[:16]}"
    request_hash = sha256_prefixed(request.model_dump_json())

    al.emit(
        event_type="conversation_event",
        event_version="1.0.0",
        severity="INFO",
        fields={
            "conversation_phase": "started",
            "agent_id": settings.analytics_service_name,
            "initial_query_hash": request_hash,
        },
        session_id=session_id,
    )

    try:
        result = await run_fund_recommend(request)
    except Exception as exc:
        al.emit(
            event_type="error_event",
            event_version="1.0.0",
            severity="ERROR",
            fields={
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:1000],
                "error_category": "internal",
                "is_retriable": False,
            },
            session_id=session_id,
        )
        al.emit(
            event_type="conversation_event",
            event_version="1.0.0",
            severity="WARN",
            fields={
                "conversation_phase": "aborted",
                "agent_id": settings.analytics_service_name,
                "initial_query_hash": request_hash,
            },
            session_id=session_id,
        )
        await al.flush()
        raise

    al.emit(
        event_type="business_event",
        event_version="1.0.0",
        severity="INFO",
        fields={
            "business_domain": "stock_analysis",
            "action": "funds_recommended",
            "resource_type": "fund_ranking",
            "resource_id": f"{request.category}:{request.horizon}",
            "attributes": _build_business_attributes(request, result),
        },
        session_id=session_id,
    )
    al.emit(
        event_type="conversation_event",
        event_version="1.0.0",
        severity="INFO",
        fields={
            "conversation_phase": "ended",
            "agent_id": settings.analytics_service_name,
            "initial_query_hash": request_hash,
        },
        session_id=session_id,
    )
    await al.flush()

    return result
