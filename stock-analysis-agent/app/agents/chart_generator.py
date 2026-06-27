import logging
import os
from pathlib import Path
from typing import List, Optional
from datetime import datetime

# Force matplotlib's headless backend before it is ever imported (Cloud Run has
# no display). Setting MPLBACKEND is import-order-safe and authoritative: it
# does not require importing matplotlib here, and keeps this module importable in
# environments where matplotlib is absent.
os.environ.setdefault("MPLBACKEND", "Agg")

from models.stock import OHLCVData
from agents.forecast import ForecastResult

logger = logging.getLogger(__name__)

# Fan-chart styling: outer band lighter than inner band.
_OUTER_BAND_ALPHA = 0.12
_INNER_BAND_ALPHA = 0.22
_FORECAST_COLOR = "#1f77b4"


def _overlay_forecast(fig, axes, n_hist: int, last_price: float, forecast: ForecastResult) -> None:
    """Draw the percentile fan onto the price axis, anchored at the last close.

    mplfinance plots candles at integer x-positions ``0..N-1``; the forecast
    occupies the following ``horizon`` positions. We anchor every projected
    series at ``(n_hist - 1, last_price)`` so the cone visually grows out of the
    final candle.
    """
    price_ax = axes[0]
    horizon = forecast.horizon_days
    xs = list(range(n_hist, n_hist + horizon))
    anchor_x = n_hist - 1

    bands = forecast.bands
    percentiles = sorted(bands.keys())

    # Outer band (e.g. 10-90) and inner band (e.g. 25-75) if available.
    lo, hi = percentiles[0], percentiles[-1]
    price_ax.fill_between(
        xs, bands[lo], bands[hi], color=_FORECAST_COLOR, alpha=_OUTER_BAND_ALPHA,
        linewidth=0, label=f"P{lo}-P{hi}",
    )
    if len(percentiles) >= 4:
        inner_lo, inner_hi = percentiles[1], percentiles[-2]
        price_ax.fill_between(
            xs, bands[inner_lo], bands[inner_hi], color=_FORECAST_COLOR,
            alpha=_INNER_BAND_ALPHA, linewidth=0, label=f"P{inner_lo}-P{inner_hi}",
        )

    # Median path as a dashed line, anchored to the last actual close.
    if 50 in bands:
        price_ax.plot(
            [anchor_x] + xs, [last_price] + list(bands[50]), color=_FORECAST_COLOR,
            linestyle="--", linewidth=1.2, label="Forecast median",
        )

    price_ax.legend(loc="upper left", fontsize=7, framealpha=0.6)


def generate_chart(
    ticker: str,
    ohlcv: List[OHLCVData],
    charts_dir: str = "data/charts",
    forecast: Optional[ForecastResult] = None,
) -> Optional[str]:
    """Generate an OHLCV candlestick chart, optionally with a forecast fan overlay.

    Returns the saved file path, or None if charting is unavailable / fails.
    The forecast is a statistical simulation, not investment advice; numbers come
    from the simulation, never from an LLM.
    """
    if not ohlcv:
        return None

    try:
        import mplfinance as mpf
        import pandas as pd

        df = pd.DataFrame([{
            "Date": r.date,
            "Open": r.open,
            "High": r.high,
            "Low": r.low,
            "Close": r.close,
            "Volume": r.volume,
        } for r in ohlcv])
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date")

        Path(charts_dir).mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{ticker}_{timestamp}.png"
        filepath = os.path.join(charts_dir, filename)

        plot_df = df
        title = f"{ticker} Stock Chart"
        if forecast is not None and forecast.bands:
            # Reserve x-axis room for the forecast horizon with blank future rows.
            future_idx = pd.to_datetime(forecast.dates)
            blank = pd.DataFrame(index=future_idx, columns=df.columns, dtype=float)
            plot_df = pd.concat([df, blank])
            title = f"{ticker} Stock Chart + {forecast.horizon_days}d Forecast"

        if forecast is not None and forecast.bands:
            fig, axes = mpf.plot(
                plot_df,
                type="candle",
                style="charles",
                title=title,
                volume=True,
                mav=(20, 50),
                returnfig=True,
                warn_too_much_data=len(plot_df) + 10,
            )
            _overlay_forecast(fig, axes, n_hist=len(df), last_price=float(df["Close"].iloc[-1]), forecast=forecast)
            fig.savefig(filepath)
            import matplotlib.pyplot as plt
            plt.close(fig)
        else:
            mpf.plot(
                plot_df,
                type="candle",
                style="charles",
                title=title,
                volume=True,
                mav=(20, 50),
                savefig=filepath,
            )

        logger.info("Chart saved to %s", filepath)
        return filepath
    except ImportError:
        logger.warning("mplfinance not installed, skipping chart generation")
        return None
    except Exception as e:
        logger.error("Failed to generate chart for %s: %s", ticker, e)
        return None
