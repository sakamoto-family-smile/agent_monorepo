import logging
from fastapi import APIRouter
from models.stock import ScreenerRequest, ScreenerResult
from agents.screener import run_screener

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/screen", response_model=ScreenerResult)
async def screen_stocks(request: ScreenerRequest) -> ScreenerResult:
    """
    短期上昇候補スクリーニングを実行する。

    - market: "JP"（日本株）/ "US"（米国株）/ "ALL"（両方）
    - top_n: 上位何件を返すか（最大50）
    - rsi_max: RSI上限（デフォルト45）
    - volume_spike_min: 出来高スパイク最小倍率（デフォルト1.5倍）
    - require_macd_cross: MACDゴールデンクロスを必須条件にする
    - require_price_above_sma20: SMA20超えを必須条件にする
    """
    logger.info("Screen request: market=%s top_n=%d", request.market, request.top_n)
    result = await run_screener(request)
    return result
