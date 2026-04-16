import logging
from typing import List, Optional

import pandas as pd

from models.stock import OHLCVData, TechnicalIndicators

logger = logging.getLogger(__name__)


def compute_indicators(ohlcv: List[OHLCVData]) -> Optional[TechnicalIndicators]:
    """Compute technical indicators from OHLCV data."""
    if len(ohlcv) < 20:
        logger.warning("Insufficient data for technical indicators (need >=20 bars, got %d)", len(ohlcv))
        return TechnicalIndicators()

    df = pd.DataFrame([{
        "date": r.date,
        "open": r.open,
        "high": r.high,
        "low": r.low,
        "close": r.close,
        "volume": r.volume,
    } for r in ohlcv])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()

    close = df["close"]

    indicators = TechnicalIndicators()

    # SMA
    if len(close) >= 20:
        indicators.sma_20 = _safe_float(close.rolling(20).mean().iloc[-1])
    if len(close) >= 50:
        indicators.sma_50 = _safe_float(close.rolling(50).mean().iloc[-1])

    # EMA
    if len(close) >= 20:
        indicators.ema_20 = _safe_float(close.ewm(span=20, adjust=False).mean().iloc[-1])

    # RSI
    if len(close) >= 15:
        indicators.rsi_14 = _safe_float(_compute_rsi(close, 14))

    # MACD
    if len(close) >= 26:
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        indicators.macd = _safe_float(macd_line.iloc[-1])
        indicators.macd_signal = _safe_float(signal_line.iloc[-1])
        indicators.macd_hist = _safe_float((macd_line - signal_line).iloc[-1])

    # Bollinger Bands
    if len(close) >= 20:
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        indicators.bb_upper = _safe_float((sma20 + 2 * std20).iloc[-1])
        indicators.bb_middle = _safe_float(sma20.iloc[-1])
        indicators.bb_lower = _safe_float((sma20 - 2 * std20).iloc[-1])

    return indicators


def _compute_rsi(close: pd.Series, period: int = 14) -> Optional[float]:
    """Compute RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    if avg_loss.iloc[-1] == 0:
        return 100.0
    rs = avg_gain.iloc[-1] / avg_loss.iloc[-1]
    return 100 - (100 / (1 + rs))


def _safe_float(value) -> Optional[float]:
    try:
        if value is None or (hasattr(value, '__class__') and value.__class__.__name__ == 'float' and str(value) == 'nan'):
            return None
        import math
        if math.isnan(float(value)):
            return None
        return round(float(value), 4)
    except Exception:
        return None
