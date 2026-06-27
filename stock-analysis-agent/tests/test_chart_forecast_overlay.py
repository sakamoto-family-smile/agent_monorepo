"""Chart generator should optionally overlay a forecast fan onto the price panel.

Visual fidelity is covered by manual/visual checks; here we only pin the
contract: passing a ForecastResult still yields a saved PNG and never raises.
"""

import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))


def _make_ohlcv(n: int = 90):
    from models.stock import OHLCVData
    import random

    rng = random.Random(11)
    records = []
    price = 1000.0
    base = date(2024, 1, 2)
    for i in range(n):
        price *= 1 + rng.gauss(0.0005, 0.012)
        records.append(
            OHLCVData(
                date=str(base + timedelta(days=i)),
                open=round(price * 0.999, 2),
                high=round(price * 1.01, 2),
                low=round(price * 0.99, 2),
                close=round(price, 2),
                volume=1_000_000 + i,
            )
        )
    return records


def test_chart_with_forecast_overlay_saves_png(tmp_path):
    from agents.chart_generator import generate_chart
    from agents.forecast import MonteCarloForecaster

    ohlcv = _make_ohlcv()
    forecast = MonteCarloForecaster(n_paths=500, seed=5).forecast(ohlcv, horizon_days=21)

    out = generate_chart("TEST.T", ohlcv, charts_dir=str(tmp_path), forecast=forecast)

    assert out is not None
    assert os.path.exists(out)
    assert os.path.getsize(out) > 0


def test_chart_without_forecast_still_works(tmp_path):
    from agents.chart_generator import generate_chart

    out = generate_chart("TEST.T", _make_ohlcv(), charts_dir=str(tmp_path))
    assert out is not None
    assert os.path.exists(out)
