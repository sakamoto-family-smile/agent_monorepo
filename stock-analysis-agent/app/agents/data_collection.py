import logging
from typing import Optional, List, Dict, Any

import yfinance as yf
import pandas as pd

from models.stock import OHLCVData, FundamentalData
from services.database import get_cached_price, set_cached_price

logger = logging.getLogger(__name__)


async def fetch_ohlcv(ticker: str, period: str = "3mo") -> List[OHLCVData]:
    """Fetch OHLCV data with caching."""
    cached = await get_cached_price(ticker, period)
    if cached:
        logger.debug("Cache hit for %s period=%s", ticker, period)
        return [OHLCVData(**item) for item in cached]

    try:
        tk = yf.Ticker(ticker)
        df = tk.history(period=period)
        if df.empty:
            logger.warning("No OHLCV data for %s", ticker)
            return []

        records = []
        for date, row in df.iterrows():
            records.append(OHLCVData(
                date=str(date.date()),
                open=round(float(row["Open"]), 4),
                high=round(float(row["High"]), 4),
                low=round(float(row["Low"]), 4),
                close=round(float(row["Close"]), 4),
                volume=int(row["Volume"]),
            ))

        # Cache the result
        await set_cached_price(ticker, period, [r.model_dump() for r in records])
        return records
    except Exception as e:
        logger.error("Failed to fetch OHLCV for %s: %s", ticker, e)
        return []


async def fetch_fundamentals(ticker: str) -> Optional[FundamentalData]:
    """Fetch fundamental data from yfinance."""
    try:
        tk = yf.Ticker(ticker)
        info = tk.info
        if not info:
            return None

        return FundamentalData(
            pe_ratio=_safe_float(info.get("trailingPE")),
            pb_ratio=_safe_float(info.get("priceToBook")),
            market_cap=_safe_float(info.get("marketCap")),
            dividend_yield=_safe_float(info.get("dividendYield")),
            revenue=_safe_float(info.get("totalRevenue")),
            net_income=_safe_float(info.get("netIncomeToCommon")),
            eps=_safe_float(info.get("trailingEps")),
            debt_to_equity=_safe_float(info.get("debtToEquity")),
            roe=_safe_float(info.get("returnOnEquity")),
            sector=info.get("sector"),
            industry=info.get("industry"),
        )
    except Exception as e:
        logger.error("Failed to fetch fundamentals for %s: %s", ticker, e)
        return None


def _safe_float(value) -> Optional[float]:
    """Safely convert to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
