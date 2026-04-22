from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class ResolveResult(BaseModel):
    ticker: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: str  # "regex", "dict", "yfinance", "llm"
    company_name: Optional[str] = None


class OHLCVData(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class TechnicalIndicators(BaseModel):
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    ema_20: Optional[float] = None
    rsi_14: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_hist: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None


class FundamentalData(BaseModel):
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    market_cap: Optional[float] = None
    dividend_yield: Optional[float] = None
    revenue: Optional[float] = None
    net_income: Optional[float] = None
    eps: Optional[float] = None
    debt_to_equity: Optional[float] = None
    roe: Optional[float] = None
    sector: Optional[str] = None
    industry: Optional[str] = None


class SentimentData(BaseModel):
    overall_sentiment: str  # "positive", "negative", "neutral"
    score: float = Field(ge=-1.0, le=1.0)
    news_items: List[Dict[str, Any]] = []
    summary: str = ""


class AnalysisRequest(BaseModel):
    query: str  # company name or ticker
    analysis_types: List[str] = ["technical", "fundamental", "sentiment"]
    period: str = "3mo"  # yfinance period


class AnalysisReport(BaseModel):
    ticker: str
    company_name: Optional[str] = None
    generated_at: datetime
    ohlcv: List[OHLCVData] = []
    technical: Optional[TechnicalIndicators] = None
    fundamental: Optional[FundamentalData] = None
    sentiment: Optional[SentimentData] = None
    chart_path: Optional[str] = None
    report_text: str = ""
    summary: str = ""


# --- Screener models ---

class ScreenerRequest(BaseModel):
    market: str = "JP"          # "JP", "US", "ALL"
    top_n: int = Field(default=20, ge=1, le=50)
    rsi_max: float = Field(default=45.0, ge=0.0, le=100.0)   # RSI上限（売られすぎ）
    rsi_min: float = Field(default=0.0, ge=0.0, le=100.0)    # RSI下限
    volume_spike_min: float = Field(default=1.5, ge=1.0)     # 出来高スパイク倍率（直近5日平均比）
    require_macd_cross: bool = False                          # MACDゴールデンクロス必須
    require_price_above_sma20: bool = False                   # SMA20超え必須
    period: str = "3mo"                                       # データ取得期間


class ScreenerCandidate(BaseModel):
    rank: int
    ticker: str
    company_name: Optional[str] = None
    current_price: float
    price_change_pct: float        # 直近5日間の騰落率
    rsi_14: Optional[float] = None
    volume_spike: Optional[float] = None   # 直近出来高 / 5日平均出来高
    macd_hist: Optional[float] = None
    above_sma20: Optional[bool] = None
    score: float                   # 総合スコア（高いほど短期上昇期待大）
    signals: List[str] = []        # 点灯しているシグナル一覧


class ScreenerResult(BaseModel):
    screened_at: datetime
    market: str
    total_scanned: int
    candidates: List[ScreenerCandidate]


# --- Fund recommendation models ---

class FundRecommendRequest(BaseModel):
    """投資信託 (ETF プロキシ) のオススメランキング取得リクエスト。"""

    category: str = Field(
        default="all",
        description="対象カテゴリ: us_index / global / dividend / sector / all",
    )
    top_n: int = Field(default=5, ge=1, le=20)
    horizon: str = Field(
        default="1y",
        description="トレンド評価期間: 3mo / 6mo / 1y / 3y",
    )
    require_uptrend: bool = Field(
        default=False,
        description="True にすると SMA50 > SMA200 (ゴールデンクロス継続) を必須化",
    )


class FundCandidate(BaseModel):
    rank: int
    ticker: str
    name: Optional[str] = None
    category: Optional[str] = None
    aliases: List[str] = []
    current_price: float
    return_1m_pct: Optional[float] = None
    return_3m_pct: Optional[float] = None
    return_horizon_pct: Optional[float] = None
    volatility_pct: Optional[float] = None       # 年率ボラティリティ (%)
    max_drawdown_pct: Optional[float] = None     # 期間内最大ドローダウン (%, 負値)
    sharpe_like: Optional[float] = None          # 年率リターン / 年率σ (リスクフリーレートは0近似)
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None
    above_sma_200: Optional[bool] = None
    score: float
    rationale: List[str] = []                    # 根拠ポイント (人間可読)


class FundRecommendResult(BaseModel):
    recommended_at: datetime
    category: str
    horizon: str
    total_scanned: int
    candidates: List[FundCandidate]
    disclaimer: str = (
        "本ランキングは情報提供のみを目的としており、投資勧誘や個別の投資助言ではありません。"
        "投資判断はご自身の責任で行ってください。"
    )
