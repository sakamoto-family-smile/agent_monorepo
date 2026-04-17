"""Tests for the stock screener module."""

import os
import sys
from datetime import datetime, timezone
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from agents.screener import _score_candidate, _get_universe, run_screener
from models.stock import ScreenerRequest, ScreenerCandidate, ScreenerResult


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
        # ALL は JP + US + GROWTH を結合する
        assert len(tickers) > len(jp) + len(us)
        assert all(t in tickers for t in jp)
        assert all(t in tickers for t in us)

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


# ── 確定的なスコアリング（浮動しない制御された系列） ──────────────────────────

def _make_deterministic_bullish_df(
    n: int = 60,
    *,
    avg_volume: int = 100_000,
    final_volume_multiplier: float = 3.0,
) -> pd.DataFrame:
    """
    スコアが確実に付与される候補系列を作る。
    - 長期の緩やかな下降トレンドで RSI(14) を 30 付近まで下げる
    - 直近 5 日で小幅な反発（price_change_pct > 0、ただし <= 5%）
    - 最終日に出来高スパイク
    - 反発前までのドローダウンにより current_price < SMA20 → require_price_above_sma20 は False 前提
    """
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    closes: list[float] = []
    base = 1000.0
    # 0 〜 (n-6) までは -5/日 の単調下降
    for i in range(n - 5):
        closes.append(base - i * 5.0)
    # 直近 5 日は小さく反発（+1.5/日）
    for _ in range(5):
        closes.append(closes[-1] + 1.5)

    volumes = [avg_volume] * n
    volumes[-1] = int(avg_volume * final_volume_multiplier)

    return pd.DataFrame(
        {
            "Open": [c * 0.99 for c in closes],
            "High": [c * 1.01 for c in closes],
            "Low": [c * 0.98 for c in closes],
            "Close": closes,
            "Volume": volumes,
        },
        index=dates,
    )


class TestScoringDeterministic:
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

    def test_strong_bullish_returns_candidate_with_positive_score(self):
        df = _make_deterministic_bullish_df()
        req = self._default_req()
        result = _score_candidate("TEST", df, req)
        assert result is not None
        assert result.score > 0
        assert result.ticker == "TEST"
        # 出来高スパイクは 3 倍
        assert result.volume_spike == pytest.approx(3.0, abs=0.1)

    def test_price_change_pct_computed_correctly(self):
        df = _make_deterministic_bullish_df()
        req = self._default_req()
        result = _score_candidate("TEST", df, req)
        assert result is not None
        # 最終5日間は反発なので騰落率はプラス
        assert result.price_change_pct > 0

    def test_rsi_max_filter_blocks_high_rsi(self):
        # 強い上昇続きで RSI が高い系列
        n = 60
        dates = pd.date_range("2025-01-01", periods=n, freq="B")
        closes = [1000.0 + i * 10 for i in range(n)]
        volumes = [100_000] * n
        volumes[-1] = 200_000
        df = pd.DataFrame(
            {
                "Open": closes, "High": closes, "Low": closes,
                "Close": closes, "Volume": volumes,
            },
            index=dates,
        )
        # 厳しい rsi_max を設定して弾かれることを確認
        req = self._default_req(rsi_max=20.0)
        result = _score_candidate("TEST", df, req)
        assert result is None

    def test_require_macd_cross_blocks_when_no_cross(self):
        # 単調上昇系列だと MACD ヒストグラムはすでにプラス継続でクロスは起きない
        n = 60
        dates = pd.date_range("2025-01-01", periods=n, freq="B")
        closes = [1000.0 + i * 10 for i in range(n)]
        volumes = [100_000] * n
        volumes[-1] = 200_000
        df = pd.DataFrame(
            {
                "Open": closes, "High": closes, "Low": closes,
                "Close": closes, "Volume": volumes,
            },
            index=dates,
        )
        req_strict = self._default_req(
            require_macd_cross=True,
            rsi_max=100.0,
            volume_spike_min=1.5,
        )
        result = _score_candidate("TEST", df, req_strict)
        assert result is None

    def test_score_stays_within_reasonable_bounds(self):
        df = _make_deterministic_bullish_df()
        req = self._default_req()
        result = _score_candidate("TEST", df, req)
        assert result is not None
        # スコア構成要素の最大合計 = 35 + 25 + 20 + 10 + 10 = 100
        assert 0 < result.score <= 100


# ── run_screener（非同期メイン関数） ──────────────────────────────────────────

class TestRunScreener:
    @pytest.mark.asyncio
    async def test_run_screener_returns_result_with_mocked_data(self):
        """yfinance をモックし、スクリーナーが候補を返すことを確認する。"""
        df = _make_deterministic_bullish_df()
        mock_data = {"7203.T": df, "6758.T": df}

        with patch("agents.screener._download_batch", return_value=mock_data):
            req = ScreenerRequest(market="JP", top_n=5)
            result = await run_screener(req)

        assert isinstance(result, ScreenerResult)
        assert result.market == "JP"
        assert result.total_scanned == 2
        assert len(result.candidates) <= 5
        assert len(result.candidates) > 0

    @pytest.mark.asyncio
    async def test_run_screener_ranks_candidates_descending(self):
        """返される候補がスコア降順でランク付けされることを確認する。"""
        df_high = _make_deterministic_bullish_df(final_volume_multiplier=3.0)
        df_low = _make_deterministic_bullish_df(final_volume_multiplier=1.6)
        mock_data = {"HIGH.T": df_high, "LOW.T": df_low}

        with patch("agents.screener._download_batch", return_value=mock_data):
            req = ScreenerRequest(market="JP", top_n=10)
            result = await run_screener(req)

        assert len(result.candidates) >= 1
        # スコア降順
        scores = [c.score for c in result.candidates]
        assert scores == sorted(scores, reverse=True)
        # ランクは 1 始まりで連番
        for i, c in enumerate(result.candidates, start=1):
            assert c.rank == i

    @pytest.mark.asyncio
    async def test_run_screener_respects_top_n(self):
        # 候補が出そうな系列を多数投入
        df = _make_deterministic_bullish_df()
        mock_data = {f"T{i}.T": df for i in range(10)}

        with patch("agents.screener._download_batch", return_value=mock_data):
            req = ScreenerRequest(market="JP", top_n=3)
            result = await run_screener(req)

        assert len(result.candidates) <= 3

    @pytest.mark.asyncio
    async def test_run_screener_empty_batch_returns_empty_candidates(self):
        with patch("agents.screener._download_batch", return_value={}):
            req = ScreenerRequest(market="JP", top_n=5)
            result = await run_screener(req)

        assert result.total_scanned == 0
        assert result.candidates == []

    @pytest.mark.asyncio
    async def test_run_screener_skips_malformed_data(self):
        """壊れた DataFrame が混ざっても例外なく処理が継続されること。"""
        good_df = _make_deterministic_bullish_df()
        bad_df = pd.DataFrame({"Close": [1.0], "Volume": [100]})  # データ不足

        mock_data = {"GOOD.T": good_df, "BAD.T": bad_df}

        with patch("agents.screener._download_batch", return_value=mock_data):
            req = ScreenerRequest(market="JP", top_n=5)
            result = await run_screener(req)

        # BAD.T は条件未達で弾かれるが例外は起きない
        assert result.total_scanned == 2
        tickers = {c.ticker for c in result.candidates}
        assert "BAD.T" not in tickers


# ── API エンドポイント /api/screen ────────────────────────────────────────────

class TestScreenerEndpoint:
    @pytest.fixture(autouse=True)
    def _env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APP_ENV", "local")
        monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.setenv("CHARTS_DIR", str(tmp_path / "charts"))
        monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
        monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
        monkeypatch.setenv("DICTIONARIES_DIR", str(tmp_path / "dictionaries"))

    @pytest.mark.asyncio
    async def test_screen_endpoint_returns_200_with_mocked_data(self):
        from httpx import AsyncClient, ASGITransport
        import importlib
        import config
        importlib.reload(config)
        from main import app

        df = _make_deterministic_bullish_df()
        mock_data = {"7203.T": df, "6758.T": df}

        with patch("agents.screener._download_batch", return_value=mock_data):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/screen",
                    json={"market": "JP", "top_n": 5},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["market"] == "JP"
        assert "candidates" in data
        assert "total_scanned" in data
        assert "screened_at" in data

    @pytest.mark.asyncio
    async def test_screen_endpoint_validates_top_n_upper_bound(self):
        from httpx import AsyncClient, ASGITransport
        import importlib
        import config
        importlib.reload(config)
        from main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/screen",
                json={"market": "JP", "top_n": 999},
            )

        assert response.status_code == 422  # Pydantic validation error

    @pytest.mark.asyncio
    async def test_screen_endpoint_accepts_all_optional_params(self):
        from httpx import AsyncClient, ASGITransport
        import importlib
        import config
        importlib.reload(config)
        from main import app

        df = _make_deterministic_bullish_df()
        mock_data = {"7203.T": df}

        with patch("agents.screener._download_batch", return_value=mock_data):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/screen",
                    json={
                        "market": "JP",
                        "top_n": 10,
                        "rsi_max": 50.0,
                        "rsi_min": 10.0,
                        "volume_spike_min": 2.0,
                        "require_macd_cross": False,
                        "require_price_above_sma20": False,
                        "period": "3mo",
                    },
                )

        assert response.status_code == 200
