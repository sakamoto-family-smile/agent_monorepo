import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))


def _make_ohlcv(n: int = 60):
    from models.stock import OHLCVData
    from datetime import date, timedelta
    import random
    random.seed(42)
    records = []
    price = 1000.0
    base_date = date(2024, 1, 2)
    for i in range(n):
        delta = random.uniform(-20, 20)
        open_p = price
        close_p = price + delta
        high_p = max(open_p, close_p) + random.uniform(0, 10)
        low_p = min(open_p, close_p) - random.uniform(0, 10)
        records.append(OHLCVData(
            date=str(base_date + timedelta(days=i)),
            open=round(open_p, 2),
            high=round(high_p, 2),
            low=round(low_p, 2),
            close=round(close_p, 2),
            volume=random.randint(1000000, 5000000),
        ))
        price = close_p
    return records


def test_compute_indicators_returns_result():
    from agents.technical_analysis import compute_indicators
    ohlcv = _make_ohlcv(60)
    result = compute_indicators(ohlcv)
    assert result is not None


def test_compute_indicators_sma():
    from agents.technical_analysis import compute_indicators
    ohlcv = _make_ohlcv(60)
    result = compute_indicators(ohlcv)
    assert result.sma_20 is not None
    assert result.sma_50 is not None


def test_compute_indicators_rsi():
    from agents.technical_analysis import compute_indicators
    ohlcv = _make_ohlcv(60)
    result = compute_indicators(ohlcv)
    if result.rsi_14 is not None:
        assert 0 <= result.rsi_14 <= 100


def test_compute_indicators_insufficient_data():
    from agents.technical_analysis import compute_indicators
    ohlcv = _make_ohlcv(5)
    result = compute_indicators(ohlcv)
    assert result is not None
    # With only 5 bars, most indicators should be None
    assert result.sma_20 is None


def test_compute_indicators_bollinger_bands():
    from agents.technical_analysis import compute_indicators
    ohlcv = _make_ohlcv(60)
    result = compute_indicators(ohlcv)
    if result.bb_upper and result.bb_lower:
        assert result.bb_upper > result.bb_lower
