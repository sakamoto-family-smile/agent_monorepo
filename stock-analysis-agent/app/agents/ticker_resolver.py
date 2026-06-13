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


def fetch_ticker_name(ticker: str) -> str | None:
    """ティッカーから企業名を best-effort で取得する (マイリスト表示用)。

    優先: ローカルのユニバース/辞書 (高速・ネットワーク不要) → yfinance.info。
    取得できなければ None (呼び出し側は ticker のみ表示にフォールバック)。
    """
    name = _local_name_for_ticker(ticker)
    if name:
        return name
    try:
        info = yf.Ticker(ticker).info
    except Exception as e:  # noqa: BLE001 — 名前取得失敗で機能を止めない
        logger.debug("yfinance name lookup failed for %s: %s", ticker, e)
        return None
    if not info:
        return None
    return info.get("longName") or info.get("shortName") or None


def _local_name_for_ticker(ticker: str) -> str | None:
    """data/universe/*.json と seed 銘柄からティッカー→企業名を引く (ネットワーク不要)。"""
    t = ticker.upper()
    try:
        from agents.universe import _UNIVERSE_DIR  # noqa: PLC0415
    except Exception:
        return None
    import json
    from pathlib import Path

    for fname in ("jp.json", "us.json", "growth.json", "funds.json"):
        path = Path(_UNIVERSE_DIR) / fname
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for entry in data.get("tickers", []):
            if str(entry.get("ticker", "")).upper() == t and entry.get("name"):
                return entry["name"]
    return None


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
