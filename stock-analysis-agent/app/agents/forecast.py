"""Short-horizon price forecasting.

The model is deliberately hidden behind a small ``Forecaster`` Protocol so the
logic can be swapped (Monte Carlo today, ARIMA / ML tomorrow) without touching
the chart generator, the orchestrator, or the LINE delivery layer.

The default implementation, :class:`MonteCarloForecaster`, is a Geometric
Brownian Motion (GBM) simulation: drift (mu) and volatility (sigma) are
estimated from historical daily log returns, then N price paths are simulated
over the requested horizon and reduced to percentile bands (the "fan chart").

This is a statistical simulation, NOT investment advice. Numbers are produced by
the simulation here — never by an LLM — to avoid hallucinated price targets.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Protocol, Sequence, Tuple, runtime_checkable

from models.stock import OHLCVData

# Default fan-chart percentiles and a ~1 trading-month horizon.
DEFAULT_PERCENTILES: Tuple[int, ...] = (10, 25, 50, 75, 90)
DEFAULT_HORIZON_DAYS: int = 21
DEFAULT_N_PATHS: int = 2000
DEFAULT_SEED: int = 42
TRADING_DAYS_PER_YEAR: int = 252


@dataclass(frozen=True)
class ForecastResult:
    """Immutable forecast output.

    ``bands`` maps each percentile (e.g. ``50``) to a tuple of projected prices,
    one per future trading day. ``dates`` holds the matching business-day labels.
    Tuples are used (not lists) so the financial figures cannot be mutated in
    place by a downstream caller.
    """

    horizon_days: int
    percentiles: Tuple[int, ...]
    bands: Dict[int, Tuple[float, ...]]
    dates: Tuple[str, ...]
    last_price: float
    last_date: str

    @property
    def median(self) -> Tuple[float, ...]:
        """Convenience accessor for the p50 path (falls back to first band)."""
        if 50 in self.bands:
            return self.bands[50]
        return self.bands[self.percentiles[0]]


@runtime_checkable
class Forecaster(Protocol):
    """Anything that turns a price history into a :class:`ForecastResult`."""

    def forecast(
        self, ohlcv: Sequence[OHLCVData], horizon_days: int
    ) -> ForecastResult:  # pragma: no cover - structural typing only
        ...


def _next_business_days(start: date, count: int) -> List[str]:
    """Return ``count`` ISO dates following ``start``, skipping weekends.

    NOTE: Japanese exchange holidays (Golden Week, etc.) are NOT excluded — these
    labels are an approximate calendar for the x-axis, not exact TSE sessions.
    """
    out: List[str] = []
    cursor = start
    while len(out) < count:
        cursor = cursor + timedelta(days=1)
        if cursor.weekday() < 5:  # Mon-Fri
            out.append(cursor.isoformat())
    return out


def _log_returns(closes: Sequence[float]) -> List[float]:
    returns: List[float] = []
    for prev, cur in zip(closes, closes[1:]):
        if prev > 0 and cur > 0:
            returns.append(math.log(cur / prev))
    return returns


class MonteCarloForecaster:
    """GBM Monte Carlo fan-chart forecaster.

    Parameters are estimated from the supplied history, so the same instance can
    forecast any ticker. RNG is seeded for reproducible, testable output.
    """

    def __init__(
        self,
        n_paths: int = DEFAULT_N_PATHS,
        seed: int = DEFAULT_SEED,
        percentiles: Sequence[int] = DEFAULT_PERCENTILES,
    ) -> None:
        if n_paths <= 0:
            raise ValueError("n_paths must be positive")
        self.n_paths = n_paths
        self.seed = seed
        self.percentiles: Tuple[int, ...] = tuple(percentiles)

    def forecast(
        self, ohlcv: Sequence[OHLCVData], horizon_days: int = DEFAULT_HORIZON_DAYS
    ) -> ForecastResult:
        if horizon_days <= 0:
            raise ValueError("horizon_days must be positive")

        closes = [r.close for r in ohlcv]
        returns = _log_returns(closes)
        if len(returns) < 1:
            raise ValueError(
                "insufficient price history for forecasting (need >= 2 closes)"
            )

        import numpy as np

        log_rets = np.asarray(returns, dtype=float)
        mu = float(log_rets.mean())
        sigma = float(log_rets.std(ddof=1)) if len(log_rets) > 1 else 0.0

        if sigma <= 0.0:
            # Zero volatility (constant prices / too few points) would collapse
            # every percentile onto one line — a misleading "fan". Refuse instead.
            raise ValueError(
                "zero volatility: insufficient price variation to simulate a forecast"
            )

        last_price = float(closes[-1])
        last_date = ohlcv[-1].date

        rng = np.random.default_rng(self.seed)
        drift = mu - 0.5 * sigma * sigma

        # (n_paths, horizon) standard normals -> per-step log increments.
        shocks = rng.standard_normal((self.n_paths, horizon_days))
        increments = drift + sigma * shocks
        cumulative = np.cumsum(increments, axis=1)
        paths = last_price * np.exp(cumulative)  # (n_paths, horizon)

        pct_values = np.percentile(paths, self.percentiles, axis=0)  # (P, horizon)
        bands: Dict[int, Tuple[float, ...]] = {
            int(p): tuple(float(v) for v in pct_values[i])
            for i, p in enumerate(self.percentiles)
        }

        dates = tuple(_next_business_days(date.fromisoformat(last_date), horizon_days))

        return ForecastResult(
            horizon_days=horizon_days,
            percentiles=self.percentiles,
            bands=bands,
            dates=dates,
            last_price=last_price,
            last_date=last_date,
        )


# Module-level default instance for callers that don't need custom params.
default_forecaster: Forecaster = MonteCarloForecaster()
