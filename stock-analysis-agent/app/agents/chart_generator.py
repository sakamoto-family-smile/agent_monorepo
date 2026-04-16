import logging
import os
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from models.stock import OHLCVData

logger = logging.getLogger(__name__)


def generate_chart(ticker: str, ohlcv: List[OHLCVData], charts_dir: str = "data/charts") -> Optional[str]:
    """Generate OHLCV candlestick chart and save to file. Returns file path or None."""
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

        mpf.plot(
            df,
            type="candle",
            style="charles",
            title=f"{ticker} Stock Chart",
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
