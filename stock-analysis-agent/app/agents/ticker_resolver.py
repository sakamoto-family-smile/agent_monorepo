import re
import logging
from dataclasses import dataclass

import yfinance as yf

from models.stock import ResolveResult
from services.database import lookup_ticker

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TickerCandidate:
    """曖昧な企業名入力に対する候補 1 件 (PROPOSAL-0011 follow-up)。"""

    ticker: str
    name: str | None = None
    exchange: str | None = None


def search_candidates(query: str, *, max_results: int = 5) -> list[TickerCandidate]:
    """yfinance Search で候補を最大 max_results 件返す (LINE の候補提示用)。

    失敗・ゼロ件は空 list (呼び出し側が「見つからない」案内を出す)。
    """
    try:
        results = yf.Search(query, max_results=max_results)
        quotes = results.quotes if hasattr(results, "quotes") else []
    except Exception as e:
        logger.debug("yfinance Search failed for %s: %s", query, e)
        return []
    candidates: list[TickerCandidate] = []
    seen: set[str] = set()
    for q in quotes or []:
        symbol = (q.get("symbol") or "").strip()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        candidates.append(
            TickerCandidate(
                ticker=symbol,
                name=q.get("longname") or q.get("shortname"),
                exchange=q.get("exchDisp") or q.get("exchange"),
            )
        )
        if len(candidates) >= max_results:
            break
    return candidates

# Ticker pattern: alphanumeric + dots/hyphens, 1-10 chars
TICKER_PATTERN = re.compile(r'^[A-Z0-9]{1,6}(\.[A-Z]{1,2})?$|^[A-Z0-9]{1,6}-[A-Z]{1,2}$')

# Common Japanese ticker patterns (4-5 digit codes)
JP_TICKER_PATTERN = re.compile(r'^\d{4,5}(\.T)?$')


async def resolve_ticker(query: str) -> ResolveResult:
    """
    Resolve company name/query to a ticker symbol via 4-step fallback.

    Step 1: Regex check (already looks like a ticker)
    Step 2: Local dictionary lookup (SQLite)
    Step 3: yfinance search
    Step 4: Claude LLM fallback
    """
    query = query.strip()

    # Step 1: Regex - already looks like ticker
    upper = query.upper()
    if TICKER_PATTERN.match(upper):
        # Add .T suffix for bare Japanese codes
        ticker = upper if '.' in upper or not upper.isdigit() else f"{upper}.T"
        if JP_TICKER_PATTERN.match(upper) and '.' not in upper:
            ticker = f"{upper}.T"
        return ResolveResult(
            ticker=ticker,
            confidence=0.95,
            source="regex",
            company_name=None,
        )

    if JP_TICKER_PATTERN.match(query):
        ticker = query if query.endswith('.T') else f"{query}.T"
        return ResolveResult(
            ticker=ticker,
            confidence=0.95,
            source="regex",
            company_name=None,
        )

    # Step 2: Local dictionary
    result = await lookup_ticker(query)
    if result:
        return ResolveResult(
            ticker=result["ticker"],
            confidence=0.90,
            source="dict",
            company_name=result["company_name"],
        )

    # Step 3: yfinance search
    try:
        ticker_obj = yf.Ticker(query)
        info = ticker_obj.info
        if info and info.get("symbol"):
            return ResolveResult(
                ticker=info["symbol"],
                confidence=0.75,
                source="yfinance",
                company_name=info.get("longName"),
            )
    except Exception as e:
        logger.debug("yfinance search failed for %s: %s", query, e)

    # yfinance search API
    try:
        results = yf.Search(query, max_results=5)
        quotes = results.quotes if hasattr(results, 'quotes') else []
        if quotes:
            best = quotes[0]
            return ResolveResult(
                ticker=best.get("symbol", query.upper()),
                confidence=0.70,
                source="yfinance",
                company_name=best.get("longname") or best.get("shortname"),
            )
    except Exception as e:
        logger.debug("yfinance Search failed for %s: %s", query, e)

    # Step 4: LLM fallback - return low confidence with best guess
    logger.warning("Could not resolve ticker for query: %s, using LLM fallback placeholder", query)
    return ResolveResult(
        ticker=query.upper().replace(" ", ""),
        confidence=0.30,
        source="llm",
        company_name=query,
    )
