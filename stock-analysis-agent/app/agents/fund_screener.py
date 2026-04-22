"""
投資信託 (ETF プロキシ) のオススメランキング生成。

`data/universe/funds.json` のキュレーション済み ETF を対象に、
価格時系列ベースのトレンド指標 (リターン / ボラティリティ / ドローダウン /
SMA50・SMA200) からスコアを算出し、ランキングと根拠 (rationale) を返す。

設計方針:
  - yfinance のみで取得可能な指標に限定 (経費率・AUM 等は対象外)
  - 個別株向けの `screener.py` と独立 (シグナル / 評価期間が異なるため)
  - 投資勧誘ではなく情報提供であることを呼び出し側が明示できるよう、
    結果モデル側にディスクレーマを持たせている (FundRecommendResult.disclaimer)
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf

from models.stock import FundCandidate, FundRecommendRequest, FundRecommendResult

logger = logging.getLogger(__name__)

_UNIVERSE_PATH = Path(__file__).resolve().parents[2] / "data" / "universe" / "funds.json"

# 評価期間 (horizon) → yfinance の period / 必要最小バー数
_HORIZON_TO_PERIOD: Dict[str, Tuple[str, int]] = {
    "3mo": ("6mo", 50),
    "6mo": ("1y", 100),
    "1y": ("2y", 200),
    "3y": ("5y", 500),
}

# 営業日換算 (年率化用)
_TRADING_DAYS = 252


# ── ユニバース読込 ────────────────────────────────────────────────────────────

def load_funds_universe() -> List[Dict[str, object]]:
    """funds.json を読み込んで {ticker, name, category, aliases} のリストを返す。

    ファイル不在 / パース失敗時は空リストを返し、呼び出し側で例外を受けない。
    """
    if not _UNIVERSE_PATH.exists():
        logger.warning("Funds universe not found: %s", _UNIVERSE_PATH)
        return []

    try:
        data = json.loads(_UNIVERSE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.error("Failed to read funds universe: %s", e)
        return []

    raw_tickers = data.get("tickers", [])
    out: List[Dict[str, object]] = []
    for entry in raw_tickers:
        if not isinstance(entry, dict) or "ticker" not in entry:
            continue
        out.append(
            {
                "ticker": entry["ticker"],
                "name": entry.get("name"),
                "category": entry.get("category"),
                "aliases": list(entry.get("aliases", []) or []),
            }
        )
    return out


def _filter_by_category(
    universe: List[Dict[str, object]], category: str
) -> List[Dict[str, object]]:
    if category.lower() == "all":
        return list(universe)
    cat = category.lower()
    return [e for e in universe if str(e.get("category", "")).lower() == cat]


# ── 指標計算 ──────────────────────────────────────────────────────────────────

def _safe_float(x) -> Optional[float]:
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def _return_pct(close: pd.Series, lookback_days: int) -> Optional[float]:
    """直近価格と lookback_days 前の価格の騰落率 (%)。"""
    if len(close) <= lookback_days:
        return None
    base = float(close.iloc[-1 - lookback_days])
    last = float(close.iloc[-1])
    if base <= 0:
        return None
    return (last - base) / base * 100.0


def _max_drawdown_pct(close: pd.Series) -> Optional[float]:
    """期間内の最大ドローダウン (%, 負値)。データ不足時は None。"""
    if len(close) < 2:
        return None
    cummax = close.cummax()
    dd = (close - cummax) / cummax
    val = float(dd.min())
    if math.isnan(val):
        return None
    return val * 100.0


def _annualized_volatility_pct(close: pd.Series) -> Optional[float]:
    """日次対数収益率の標準偏差を年率化 (%)。"""
    if len(close) < 20:
        return None
    rets = pd.Series(close).pct_change().dropna()
    if len(rets) < 20:
        return None
    sigma = float(rets.std())
    if math.isnan(sigma) or sigma == 0:
        return None
    return sigma * math.sqrt(_TRADING_DAYS) * 100.0


def _annualized_return_pct(close: pd.Series) -> Optional[float]:
    """期間トータルリターンを年率換算 (%)。"""
    if len(close) < 2:
        return None
    base = float(close.iloc[0])
    last = float(close.iloc[-1])
    if base <= 0:
        return None
    total_ret = last / base
    years = len(close) / _TRADING_DAYS
    if years <= 0:
        return None
    try:
        ann = total_ret ** (1.0 / years) - 1.0
    except (ValueError, OverflowError):
        return None
    return ann * 100.0


def _sma(close: pd.Series, window: int) -> Optional[float]:
    if len(close) < window:
        return None
    val = float(close.rolling(window).mean().iloc[-1])
    if math.isnan(val):
        return None
    return val


# ── スコアリング ──────────────────────────────────────────────────────────────


def _score_fund(
    entry: Dict[str, object],
    df: pd.DataFrame,
    req: FundRecommendRequest,
) -> Optional[FundCandidate]:
    """1ファンド分の OHLCV からスコアと根拠を計算する。"""
    if df is None or df.empty or "Close" not in df.columns:
        return None

    close = df["Close"].dropna()
    horizon_period, min_bars = _HORIZON_TO_PERIOD.get(req.horizon, ("2y", 200))
    if len(close) < max(60, min_bars // 4):  # 最低でも約3ヶ月分は欲しい
        return None

    current_price = _safe_float(close.iloc[-1])
    if current_price is None or current_price <= 0:
        return None

    # 各種指標
    ret_1m = _return_pct(close, 21)
    ret_3m = _return_pct(close, 63)
    # horizon リターン: horizon 期間相当の lookback
    horizon_lookback = {"3mo": 63, "6mo": 126, "1y": 252, "3y": 756}.get(
        req.horizon, 252
    )
    ret_horizon = _return_pct(close, min(horizon_lookback, len(close) - 1))

    vol_pct = _annualized_volatility_pct(close)
    dd_pct = _max_drawdown_pct(close)
    ann_ret = _annualized_return_pct(close)

    sharpe_like: Optional[float] = None
    if ann_ret is not None and vol_pct is not None and vol_pct > 0:
        sharpe_like = round(ann_ret / vol_pct, 3)

    sma_50 = _sma(close, 50)
    sma_200 = _sma(close, 200) if len(close) >= 200 else None
    above_sma_200 = (
        current_price > sma_200 if (sma_200 is not None) else None
    )

    # require_uptrend: SMA50 > SMA200 を必須化
    if req.require_uptrend:
        if sma_50 is None or sma_200 is None:
            return None
        if not (sma_50 > sma_200 and above_sma_200 is True):
            return None

    # ── スコア計算 (0〜100点) ───────────────────────────────────────────────
    score = 0.0
    rationale: List[str] = []

    # 1) horizon リターン (最大35点)
    if ret_horizon is not None:
        if ret_horizon >= 30:
            score += 35
            rationale.append(f"{req.horizon}リターン+{ret_horizon:.1f}% (強いトレンド)")
        elif ret_horizon >= 15:
            score += 25
            rationale.append(f"{req.horizon}リターン+{ret_horizon:.1f}% (堅調)")
        elif ret_horizon >= 5:
            score += 15
            rationale.append(f"{req.horizon}リターン+{ret_horizon:.1f}%")
        elif ret_horizon >= 0:
            score += 5
            rationale.append(f"{req.horizon}リターン+{ret_horizon:.1f}% (横ばい)")
        else:
            rationale.append(f"{req.horizon}リターン{ret_horizon:.1f}% (マイナス)")

    # 2) 短期モメンタム (最大15点) — 1ヶ月リターン
    if ret_1m is not None:
        if 0 < ret_1m <= 8:
            score += 15
            rationale.append(f"直近1ヶ月+{ret_1m:.1f}% (健全な短期上昇)")
        elif ret_1m > 8:
            score += 8
            rationale.append(f"直近1ヶ月+{ret_1m:.1f}% (急騰、過熱注意)")
        elif ret_1m > -3:
            score += 5
            rationale.append(f"直近1ヶ月{ret_1m:+.1f}% (横ばい)")

    # 3) リスク調整後リターン (最大25点) — Sharpe-like 高いほど良
    if sharpe_like is not None:
        if sharpe_like >= 1.5:
            score += 25
            rationale.append(f"リスク調整後リターン優秀 (年率リターン/σ={sharpe_like})")
        elif sharpe_like >= 1.0:
            score += 18
            rationale.append(f"リスク調整後リターン良好 (年率リターン/σ={sharpe_like})")
        elif sharpe_like >= 0.5:
            score += 10
            rationale.append(f"リスク調整後リターン中庸 (年率リターン/σ={sharpe_like})")

    # 4) ドローダウン耐性 (最大15点) — 浅いほど良 (負値)
    if dd_pct is not None:
        if dd_pct >= -10:
            score += 15
            rationale.append(f"最大ドローダウン{dd_pct:.1f}% (下落耐性 高)")
        elif dd_pct >= -20:
            score += 10
            rationale.append(f"最大ドローダウン{dd_pct:.1f}% (下落耐性 中)")
        elif dd_pct >= -30:
            score += 3
            rationale.append(f"最大ドローダウン{dd_pct:.1f}% (やや大きい)")
        else:
            rationale.append(f"最大ドローダウン{dd_pct:.1f}% (深い、リスク留意)")

    # 5) 中長期トレンド (最大10点) — SMA50 > SMA200 (ゴールデンクロス継続)
    if sma_50 is not None and sma_200 is not None:
        if sma_50 > sma_200 and above_sma_200:
            score += 10
            rationale.append("SMA50 > SMA200 かつ価格が SMA200 超え (中長期トレンド良好)")
        elif above_sma_200:
            score += 5
            rationale.append("価格が SMA200 超え")

    if score == 0 and not rationale:
        return None

    return FundCandidate(
        rank=0,  # 後でランク付け
        ticker=str(entry["ticker"]),
        name=entry.get("name") if isinstance(entry.get("name"), str) else None,
        category=entry.get("category") if isinstance(entry.get("category"), str) else None,
        aliases=[str(a) for a in entry.get("aliases", []) or []],
        current_price=round(current_price, 2),
        return_1m_pct=round(ret_1m, 2) if ret_1m is not None else None,
        return_3m_pct=round(ret_3m, 2) if ret_3m is not None else None,
        return_horizon_pct=round(ret_horizon, 2) if ret_horizon is not None else None,
        volatility_pct=round(vol_pct, 2) if vol_pct is not None else None,
        max_drawdown_pct=round(dd_pct, 2) if dd_pct is not None else None,
        sharpe_like=sharpe_like,
        sma_50=round(sma_50, 2) if sma_50 is not None else None,
        sma_200=round(sma_200, 2) if sma_200 is not None else None,
        above_sma_200=above_sma_200,
        score=round(score, 1),
        rationale=rationale,
    )


# ── データ取得 ────────────────────────────────────────────────────────────────


def _download_batch(tickers: List[str], period: str) -> Dict[str, pd.DataFrame]:
    """yfinance バッチダウンロード。エラーは吸収して空 dict を返す。"""
    if not tickers:
        return {}

    try:
        raw = yf.download(
            tickers,
            period=period,
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        logger.error("Funds batch download failed: %s", e)
        return {}

    result: Dict[str, pd.DataFrame] = {}
    if len(tickers) == 1:
        result[tickers[0]] = raw
        return result

    for ticker in tickers:
        try:
            df = raw[ticker]
            if not df.empty:
                result[ticker] = df
        except (KeyError, TypeError):
            continue
    return result


# ── メイン関数 ────────────────────────────────────────────────────────────────


async def run_fund_recommend(req: FundRecommendRequest) -> FundRecommendResult:
    """カテゴリ指定でファンドをランキングして返す。"""
    universe = _filter_by_category(load_funds_universe(), req.category)
    logger.info(
        "Fund recommend start: category=%s, candidates=%d, horizon=%s",
        req.category, len(universe), req.horizon,
    )

    if not universe:
        return FundRecommendResult(
            recommended_at=datetime.now(timezone.utc),
            category=req.category,
            horizon=req.horizon,
            total_scanned=0,
            candidates=[],
        )

    period, _ = _HORIZON_TO_PERIOD.get(req.horizon, ("2y", 200))
    tickers = [str(e["ticker"]) for e in universe]

    loop = asyncio.get_event_loop()
    batch = await loop.run_in_executor(None, _download_batch, tickers, period)
    logger.info("Funds downloaded: %d / %d", len(batch), len(tickers))

    # entry を ticker で引けるよう辞書化
    by_ticker = {str(e["ticker"]): e for e in universe}

    candidates: List[FundCandidate] = []
    for ticker, df in batch.items():
        try:
            cand = _score_fund(by_ticker[ticker], df, req)
            if cand is not None:
                candidates.append(cand)
        except Exception as e:
            logger.debug("Fund scoring failed for %s: %s", ticker, e)

    candidates.sort(key=lambda c: c.score, reverse=True)
    top = candidates[: req.top_n]
    for i, c in enumerate(top, start=1):
        c.rank = i

    logger.info("Fund recommend done: %d candidates", len(top))
    return FundRecommendResult(
        recommended_at=datetime.now(timezone.utc),
        category=req.category,
        horizon=req.horizon,
        total_scanned=len(batch),
        candidates=top,
    )
