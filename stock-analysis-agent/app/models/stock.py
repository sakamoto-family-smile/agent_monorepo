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
