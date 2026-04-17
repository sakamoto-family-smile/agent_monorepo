"""
短期上昇候補スクリーナー

対象市場の銘柄を一括スキャンし、以下の条件に基づいてスコアリングする：
  - RSI が売られすぎ圏（デフォルト 45 以下）
  - 出来高スパイク（直近出来高 / 5日平均出来高 が閾値以上）
  - MACD ヒストグラムがプラス転換（ゴールデンクロス系）
  - 株価が SMA20 を上回る（短期上昇モメンタム）
  - 直近 5 日間の騰落率
"""

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import List, Optional

import pandas as pd
import yfinance as yf

from models.stock import ScreenerCandidate, ScreenerRequest, ScreenerResult

logger = logging.getLogger(__name__)

# ── 銘柄ユニバース ────────────────────────────────────────────────────────────

# 日経225 主要構成銘柄（代表的な流動性の高い銘柄）
_JP_TICKERS: List[str] = [
    "7203.T",  # トヨタ自動車
    "6758.T",  # ソニーグループ
    "9984.T",  # ソフトバンクグループ
    "7974.T",  # 任天堂
    "6861.T",  # キーエンス
    "8306.T",  # 三菱UFJフィナンシャル
    "6098.T",  # リクルートホールディングス
    "4063.T",  # 信越化学工業
    "6367.T",  # ダイキン工業
    "8035.T",  # 東京エレクトロン
    "4519.T",  # 中外製薬
    "9432.T",  # NTT
    "7741.T",  # HOYA
    "6954.T",  # ファナック
    "4568.T",  # 第一三共
    "8316.T",  # 三井住友フィナンシャルG
    "9433.T",  # KDDI
    "7267.T",  # 本田技研工業
    "4502.T",  # 武田薬品工業
    "6501.T",  # 日立製作所
    "6702.T",  # 富士通
    "7751.T",  # キヤノン
    "8411.T",  # みずほフィナンシャルG
    "9020.T",  # 東日本旅客鉄道
    "4661.T",  # オリエンタルランド
    "6503.T",  # 三菱電機
    "6594.T",  # 日本電産（ニデック）
    "4543.T",  # テルモ
    "7832.T",  # バンダイナムコホールディングス
    "2802.T",  # 味の素
    "9022.T",  # 東海旅客鉄道
    "4901.T",  # 富士フイルムホールディングス
    "7733.T",  # オリンパス
    "6723.T",  # ルネサスエレクトロニクス
    "7201.T",  # 日産自動車
    "4307.T",  # 野村総合研究所
    "9613.T",  # NTTデータグループ
    "2914.T",  # 日本たばこ産業
    "8801.T",  # 三井不動産
    "3382.T",  # セブン＆アイ・ホールディングス
    "4813.T",  # ACCESS
    "6146.T",  # ディスコ
    "6920.T",  # レーザーテック
    "4911.T",  # 資生堂
    "9064.T",  # ヤマトホールディングス
    "7269.T",  # スズキ
    "6902.T",  # デンソー
    "8002.T",  # 丸紅
    "8058.T",  # 三菱商事
    "8031.T",  # 三井物産
]

# 米国主要銘柄（S&P500 大型株）
_US_TICKERS: List[str] = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
    "META", "TSLA", "AVGO", "ORCL", "AMD",
    "NFLX", "ADBE", "CRM", "INTC", "QCOM",
    "TXN", "MU", "AMAT", "LRCX", "KLAC",
    "JPM", "BAC", "GS", "MS", "WFC",
    "JNJ", "UNH", "PFE", "MRK", "ABBV",
    "XOM", "CVX", "COP", "EOG", "SLB",
    "AMGN", "GILD", "REGN", "VRTX", "BMY",
    "V", "MA", "PYPL", "AXP", "COF",
    "DIS", "CMCSA", "T", "VZ", "NFLX",
]


def _get_universe(market: str) -> List[str]:
    market = market.upper()
    if market == "JP":
        return _JP_TICKERS
    if market == "US":
        return _US_TICKERS
    return _JP_TICKERS + _US_TICKERS


# ── スコアリング ──────────────────────────────────────────────────────────────

def _score_candidate(
    ticker: str,
    df: pd.DataFrame,
    req: ScreenerRequest,
) -> Optional[ScreenerCandidate]:
    """
    1銘柄分のOHLCVデータからスコアを計算する。
    条件未達または計算不能な場合は None を返す。
    """
    if df is None or len(df) < 22:
        return None

    close = df["Close"].dropna()
    volume = df["Volume"].dropna()
    if len(close) < 22:
        return None

    # ── 基本値 ───────────────────────────────────────────────────────────────
    current_price = float(close.iloc[-1])
    price_5d_ago = float(close.iloc[-6]) if len(close) >= 6 else float(close.iloc[0])
    price_change_pct = (current_price - price_5d_ago) / price_5d_ago * 100

    # ── 出来高スパイク ────────────────────────────────────────────────────────
    recent_vol = float(volume.iloc[-1])
    avg_vol_5d = float(volume.iloc[-6:-1].mean()) if len(volume) >= 6 else float(volume.mean())
    volume_spike = recent_vol / avg_vol_5d if avg_vol_5d > 0 else 1.0

    # ── RSI(14) ───────────────────────────────────────────────────────────────
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta).clip(lower=0).rolling(14).mean()
    rsi_14: Optional[float] = None
    if not (math.isnan(float(gain.iloc[-1])) or float(loss.iloc[-1]) == 0):
        rs = float(gain.iloc[-1]) / float(loss.iloc[-1])
        rsi_14 = round(100 - (100 / (1 + rs)), 2)
    elif float(loss.iloc[-1]) == 0:
        rsi_14 = 100.0

    # ── SMA20 ─────────────────────────────────────────────────────────────────
    sma20 = float(close.rolling(20).mean().iloc[-1])
    above_sma20 = current_price > sma20

    # ── MACD ──────────────────────────────────────────────────────────────────
    macd_hist: Optional[float] = None
    macd_hist_prev: Optional[float] = None
    if len(close) >= 26:
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        hist = macd_line - signal_line
        macd_hist = round(float(hist.iloc[-1]), 4)
        macd_hist_prev = round(float(hist.iloc[-2]), 4) if len(hist) >= 2 else None

    # ── フィルタリング ────────────────────────────────────────────────────────
    # RSI 条件チェック
    if rsi_14 is not None:
        if rsi_14 > req.rsi_max or rsi_14 < req.rsi_min:
            return None
    # 出来高スパイク条件
    if volume_spike < req.volume_spike_min:
        return None
    # SMA20 超え必須
    if req.require_price_above_sma20 and not above_sma20:
        return None
    # MACD ゴールデンクロス必須（ヒストグラムがマイナス→プラス転換）
    if req.require_macd_cross:
        if macd_hist is None or macd_hist_prev is None:
            return None
        if not (macd_hist > 0 and macd_hist_prev <= 0):
            return None

    # ── スコア計算（0〜100点） ───────────────────────────────────────────────
    score = 0.0
    signals: List[str] = []

    # RSI スコア（低いほど高スコア：売られすぎからの反発期待）
    if rsi_14 is not None:
        if rsi_14 <= 30:
            score += 35
            signals.append(f"RSI売られすぎ({rsi_14:.1f})")
        elif rsi_14 <= 40:
            score += 25
            signals.append(f"RSI低水準({rsi_14:.1f})")
        elif rsi_14 <= 45:
            score += 15
            signals.append(f"RSI中立寄り低({rsi_14:.1f})")

    # 出来高スパイク スコア
    if volume_spike >= 3.0:
        score += 25
        signals.append(f"出来高急増({volume_spike:.1f}x)")
    elif volume_spike >= 2.0:
        score += 18
        signals.append(f"出来高増加({volume_spike:.1f}x)")
    elif volume_spike >= 1.5:
        score += 10
        signals.append(f"出来高やや増加({volume_spike:.1f}x)")

    # MACD スコア
    if macd_hist is not None and macd_hist_prev is not None:
        if macd_hist > 0 and macd_hist_prev <= 0:
            score += 20
            signals.append("MACDゴールデンクロス")
        elif macd_hist > macd_hist_prev and macd_hist > 0:
            score += 10
            signals.append("MACDヒストグラム拡大")
        elif macd_hist > macd_hist_prev:
            score += 5
            signals.append("MACD改善中")

    # SMA20 スコア
    if above_sma20:
        score += 10
        signals.append("SMA20超え")

    # 騰落率 スコア（直近5日で小幅上昇は良いシグナル）
    if 0 < price_change_pct <= 5:
        score += 10
        signals.append(f"小幅上昇({price_change_pct:+.1f}%)")
    elif price_change_pct > 5:
        score += 5
        signals.append(f"上昇中({price_change_pct:+.1f}%)")

    if score == 0:
        return None

    return ScreenerCandidate(
        rank=0,  # 後でランク付け
        ticker=ticker,
        current_price=round(current_price, 2),
        price_change_pct=round(price_change_pct, 2),
        rsi_14=rsi_14,
        volume_spike=round(volume_spike, 2),
        macd_hist=macd_hist,
        above_sma20=above_sma20,
        score=round(score, 1),
        signals=signals,
    )


# ── バッチダウンロード ─────────────────────────────────────────────────────────

def _download_batch(tickers: List[str], period: str) -> dict[str, pd.DataFrame]:
    """yfinance でバッチダウンロードし、銘柄ごとのDataFrameを返す。"""
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
        logger.error("Batch download failed: %s", e)
        return {}

    result: dict[str, pd.DataFrame] = {}

    if len(tickers) == 1:
        # 単一銘柄は group_by が効かずフラットな DataFrame が返る
        result[tickers[0]] = raw
        return result

    for ticker in tickers:
        try:
            df = raw[ticker]
            if not df.empty:
                result[ticker] = df
        except (KeyError, TypeError):
            pass

    return result


# ── メイン関数 ────────────────────────────────────────────────────────────────

async def run_screener(req: ScreenerRequest) -> ScreenerResult:
    """スクリーニングを実行して結果を返す。"""
    universe = _get_universe(req.market)
    logger.info("Screener start: market=%s, tickers=%d", req.market, len(universe))

    # yfinance は同期 I/O なので executor で実行
    loop = asyncio.get_event_loop()
    batch_data = await loop.run_in_executor(
        None,
        _download_batch,
        universe,
        req.period,
    )

    logger.info("Downloaded %d tickers", len(batch_data))

    candidates: List[ScreenerCandidate] = []
    for ticker, df in batch_data.items():
        try:
            candidate = _score_candidate(ticker, df, req)
            if candidate is not None:
                candidates.append(candidate)
        except Exception as e:
            logger.debug("Scoring failed for %s: %s", ticker, e)

    # スコア降順でソートしてランク付け
    candidates.sort(key=lambda c: c.score, reverse=True)
    for i, c in enumerate(candidates[: req.top_n], start=1):
        c.rank = i

    logger.info("Screener done: %d candidates found", len(candidates))

    return ScreenerResult(
        screened_at=datetime.now(timezone.utc),
        market=req.market,
        total_scanned=len(batch_data),
        candidates=candidates[: req.top_n],
    )
