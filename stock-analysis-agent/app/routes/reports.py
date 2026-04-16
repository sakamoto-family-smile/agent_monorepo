import json
import logging
from fastapi import APIRouter, HTTPException

from services.database import get_reports

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/reports/{ticker}")
async def get_ticker_reports(ticker: str, limit: int = 10):
    """Get recent analysis reports for a ticker."""
    ticker = ticker.upper()
    reports = await get_reports(ticker, limit=min(limit, 50))
    result = []
    for r in reports:
        try:
            r["report_data"] = json.loads(r["report_data"])
        except Exception:
            pass
        result.append(r)
    return {"ticker": ticker, "reports": result}
