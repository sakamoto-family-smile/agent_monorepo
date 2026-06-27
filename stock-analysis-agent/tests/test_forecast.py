"""Tests for the price-forecast feature (Monte Carlo bands, swappable logic).

The forecaster is intentionally behind a Protocol so the Monte Carlo model can be
replaced without touching callers. These tests pin the contract:
  * shape / length of every percentile band
  * monotonic ordering of percentiles per step
  * reproducibility under a fixed seed
  * graceful failure on insufficient history
"""

import sys
import os
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))


def _make_ohlcv(n: int = 252, start: float = 1000.0, seed: int = 7):
    """Build a deterministic OHLCV series with mild drift + noise."""
    from models.stock import OHLCVData
    import random

    rng = random.Random(seed)
    records = []
    price = start
    base_date = date(2024, 1, 2)
    for i in range(n):
        ret = rng.gauss(0.0005, 0.015)  # ~0.05% drift, 1.5% daily vol
        open_p = price
        close_p = price * (1 + ret)
        high_p = max(open_p, close_p) * (1 + abs(rng.gauss(0, 0.003)))
        low_p = min(open_p, close_p) * (1 - abs(rng.gauss(0, 0.003)))
        records.append(
            OHLCVData(
                date=str(base_date + timedelta(days=i)),
                open=round(open_p, 2),
                high=round(high_p, 2),
                low=round(low_p, 2),
                close=round(close_p, 2),
                volume=1_000_000 + i,
            )
        )
        price = close_p
    return records


def _flat_ohlcv(n: int = 60, price: float = 500.0):
    """Constant-price series -> zero volatility, zero drift."""
    from models.stock import OHLCVData

    base_date = date(2024, 1, 2)
    return [
        OHLCVData(
            date=str(base_date + timedelta(days=i)),
            open=price,
            high=price,
            low=price,
            close=price,
            volume=1_000_000,
        )
        for i in range(n)
    ]


HORIZON = 21
PERCENTILES = (10, 25, 50, 75, 90)


def _forecaster(**kwargs):
    from agents.forecast import MonteCarloForecaster

    params = dict(n_paths=2000, seed=42, percentiles=PERCENTILES)
    params.update(kwargs)
    return MonteCarloForecaster(**params)


def test_result_has_band_per_percentile_each_of_horizon_length():
    result = _forecaster().forecast(_make_ohlcv(), horizon_days=HORIZON)

    assert result.horizon_days == HORIZON
    assert tuple(result.percentiles) == PERCENTILES
    for p in PERCENTILES:
        assert p in result.bands
        assert len(result.bands[p]) == HORIZON
    assert len(result.dates) == HORIZON


def test_percentiles_are_monotonic_per_step():
    result = _forecaster().forecast(_make_ohlcv(), horizon_days=HORIZON)

    for step in range(HORIZON):
        values = [result.bands[p][step] for p in PERCENTILES]
        assert values == sorted(values), f"percentiles not ordered at step {step}: {values}"


def test_median_starts_near_last_price_and_band_widens():
    ohlcv = _make_ohlcv()
    result = _forecaster().forecast(ohlcv, horizon_days=HORIZON)

    last_close = ohlcv[-1].close
    assert result.last_price == pytest.approx(last_close)
    # first-step median within ~5% of spot
    assert result.bands[50][0] == pytest.approx(last_close, rel=0.05)
    # uncertainty cone widens: p90-p10 spread grows from first to last step
    first_spread = result.bands[90][0] - result.bands[10][0]
    last_spread = result.bands[90][-1] - result.bands[10][-1]
    assert last_spread > first_spread


def test_reproducible_under_fixed_seed():
    ohlcv = _make_ohlcv()
    a = _forecaster(seed=123).forecast(ohlcv, horizon_days=HORIZON)
    b = _forecaster(seed=123).forecast(ohlcv, horizon_days=HORIZON)
    assert a.bands == b.bands


def test_different_seed_changes_paths():
    ohlcv = _make_ohlcv()
    a = _forecaster(seed=1).forecast(ohlcv, horizon_days=HORIZON)
    b = _forecaster(seed=2).forecast(ohlcv, horizon_days=HORIZON)
    assert a.bands[50] != b.bands[50]


def test_zero_volatility_series_is_rejected():
    # A constant-price series has zero volatility -> a "fan" would collapse to one
    # line. We refuse rather than emit a misleading forecast.
    with pytest.raises(ValueError):
        _forecaster().forecast(_flat_ohlcv(), horizon_days=HORIZON)


def test_bands_and_dates_are_immutable_tuples():
    result = _forecaster().forecast(_make_ohlcv(), horizon_days=HORIZON)
    assert isinstance(result.dates, tuple)
    for p in PERCENTILES:
        assert isinstance(result.bands[p], tuple)


def test_insufficient_history_raises():
    from agents.forecast import MonteCarloForecaster

    with pytest.raises(ValueError):
        MonteCarloForecaster().forecast(_flat_ohlcv(n=1), horizon_days=HORIZON)


def test_future_dates_are_business_days_after_last():
    ohlcv = _make_ohlcv()
    result = _forecaster().forecast(ohlcv, horizon_days=HORIZON)
    last = date.fromisoformat(ohlcv[-1].date)
    first_future = date.fromisoformat(result.dates[0])
    assert first_future > last
    # no weekends in the projected calendar
    for d in result.dates:
        assert date.fromisoformat(d).weekday() < 5


def test_custom_forecaster_satisfies_protocol():
    """A trivially different model can be swapped in without code changes elsewhere."""
    from agents.forecast import Forecaster, ForecastResult, MonteCarloForecaster
    from models.stock import OHLCVData

    class FlatForecaster:
        def forecast(self, ohlcv, horizon_days):
            last = ohlcv[-1].close
            return ForecastResult(
                horizon_days=horizon_days,
                percentiles=(50,),
                bands={50: [last] * horizon_days},
                dates=[ohlcv[-1].date] * horizon_days,
                last_price=last,
                last_date=ohlcv[-1].date,
            )

    def run(f: Forecaster) -> ForecastResult:
        return f.forecast(_make_ohlcv(), horizon_days=5)

    assert isinstance(run(MonteCarloForecaster()), ForecastResult)
    assert isinstance(run(FlatForecaster()), ForecastResult)
