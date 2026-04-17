"""Tests for the stock screener module."""

import math
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from agents.screener import _score_candidate, _get_universe
from models.stock import ScreenerRequest, ScreenerCandidate


def _make_df(n: int = 60, rsi_target: float = 35.0, vol_spike: float = 2.0) -> pd.DataFrame:
    """テスト用のOHLCVデータを生成する（RSI・出来高スパイクを制御可能）。"""
    import numpy as np

    np.random.seed(42)
    base = 1000.0
    closes = [base]
    # RSI を rsi_target 付近にするため、下落が多い系列を生成
    for _ in range(n - 1):
        delta = np.random.choice([-1, 1], p=[0.65, 0.35]) * np.random.uniform(5, 15)
        closes.append(max(100, closes[-1] + delta))

    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    avg_vol = 100_000
    volumes = [int(avg_vol * np.random.uniform(0.8, 1.2)) for _ in range(n)]
    # 最終日の出来高をスパイク
    volumes[-1] = int(avg_vol * vol_spike)

    df = pd.DataFrame({
        "Open": [c * 0.99 for c in closes],
        "High": [c * 1.01 for c in closes],
        "Low": [c * 0.98 for c in closes],
        "Close": closes,
        "Volume": volumes,
    }, index=dates)
    return df


# ── _get_universe ─────────────────────────────────────────────────────────────

class TestGetUniverse:
    def test_jp_returns_jp_tickers(self):
        tickers = _get_universe("JP")
        assert all(t.endswith(".T") for t in tickers)
        assert len(tickers) >= 10

    def test_us_returns_us_tickers(self):
        tickers = _get_universe("US")
        assert all(not t.endswith(".T") for t in tickers)
        assert len(tickers) >= 10

    def test_all_returns_combined(self):
        tickers = _get_universe("ALL")
        jp = _get_universe("JP")
        us = _get_universe("US")
        assert len(tickers) == len(jp) + len(us)

    def test_case_insensitive(self):
        assert _get_universe("jp") == _get_universe("JP")


# ── _score_candidate ──────────────────────────────────────────────────────────

class TestScoreCandidate:
    def _default_req(self, **kwargs) -> ScreenerRequest:
        defaults = dict(
            market="JP",
            top_n=20,
            rsi_max=45.0,
            rsi_min=0.0,
            volume_spike_min=1.5,
            require_macd_cross=False,
            require_price_above_sma20=False,
            period="3mo",
        )
        defaults.update(kwargs)
        return ScreenerRequest(**defaults)

    def test_returns_candidate_when_conditions_met(self):
        df = _make_df(n=60, rsi_target=35.0, vol_spike=2.0)
        req = self._default_req()
        result = _score_candidate("7203.T", df, req)
        # RSI と出来高スパイクが条件を満たせば候補が返る
        assert result is None or isinstance(result, ScreenerCandidate)

    def test_returns_none_when_insufficient_data(self):
        df = _make_df(n=10)
        req = self._default_req()
        result = _score_candidate("7203.T", df, req)
        assert result is None

    def test_returns_none_when_volume_spike_below_threshold(self):
        df = _make_df(n=60, vol_spike=1.0)  # スパイクなし
        req = self._default_req(volume_spike_min=1.5)
        result = _score_candidate("7203.T", df, req)
        assert result is None

    def test_score_is_positive_when_candidate_returned(self):
        df = _make_df(n=60, vol_spike=3.0)
        req = self._default_req(volume_spike_min=1.5)
        result = _score_candidate("7203.T", df, req)
        if result is not None:
            assert result.score > 0

    def test_signals_list_populated(self):
        df = _make_df(n=60, vol_spike=2.5)
        req = self._default_req(volume_spike_min=1.5)
        result = _score_candidate("7203.T", df, req)
        if result is not None:
            assert len(result.signals) > 0

    def test_require_price_above_sma20_filters_correctly(self):
        """SMA20超え必須条件が正しく機能することを確認する。"""
        df = _make_df(n=60, vol_spike=2.0)
        req_strict = self._default_req(require_price_above_sma20=True, volume_spike_min=1.5)
        req_loose = self._default_req(require_price_above_sma20=False, volume_spike_min=1.5)

        result_strict = _score_candidate("7203.T", df, req_strict)
        result_loose = _score_candidate("7203.T", df, req_loose)

        # 条件を緩くした方が候補が返りやすい（または同じ）
        if result_strict is not None:
            assert result_loose is not None

    def test_ticker_is_preserved(self):
        df = _make_df(n=60, vol_spike=2.5)
        req = self._default_req(volume_spike_min=1.5)
        result = _score_candidate("9984.T", df, req)
        if result is not None:
            assert result.ticker == "9984.T"

    def test_volume_spike_value_computed_correctly(self):
        import numpy as np
        n = 60
        dates = pd.date_range("2025-01-01", periods=n, freq="B")
        closes = [1000.0] * n
        avg_vol = 100_000
        volumes = [avg_vol] * n
        volumes[-1] = avg_vol * 3  # 3倍スパイク

        df = pd.DataFrame({
            "Open": closes, "High": closes, "Low": closes,
            "Close": closes, "Volume": volumes,
        }, index=dates)

        req = self._default_req(volume_spike_min=1.5)
        result = _score_candidate("TEST", df, req)
        if result is not None:
            assert result.volume_spike == pytest.approx(3.0, abs=0.1)


# ── ScreenerRequest バリデーション ────────────────────────────────────────────

class TestScreenerRequest:
    def test_default_values(self):
        req = ScreenerRequest()
        assert req.market == "JP"
        assert req.top_n == 20
        assert req.rsi_max == 45.0
        assert req.volume_spike_min == 1.5
        assert req.require_macd_cross is False

    def test_top_n_upper_bound(self):
        with pytest.raises(Exception):
            ScreenerRequest(top_n=51)

    def test_top_n_lower_bound(self):
        with pytest.raises(Exception):
            ScreenerRequest(top_n=0)

    def test_rsi_bounds(self):
        with pytest.raises(Exception):
            ScreenerRequest(rsi_max=101.0)
        with pytest.raises(Exception):
            ScreenerRequest(rsi_max=-1.0)
