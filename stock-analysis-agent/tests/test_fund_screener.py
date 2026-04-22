"""Tests for the fund recommendation module."""

from __future__ import annotations

from typing import Dict, List
from unittest.mock import patch

import pandas as pd
import pytest

from agents.fund_screener import (
    _filter_by_category,
    _score_fund,
    load_funds_universe,
    run_fund_recommend,
)
from models.stock import (
    FundCandidate,
    FundRecommendRequest,
    FundRecommendResult,
)


# ── テスト用 OHLCV ファクトリ ────────────────────────────────────────────────


def _make_uptrend_df(n: int = 260, daily_drift: float = 0.05) -> pd.DataFrame:
    """緩やかな右肩上がりの DataFrame。

    daily_drift = 0.05 は 1日 +0.05% (年率約 12%) 相当。
    SMA50 > SMA200 になり、Sharpe-like も健全な値になることを意図する。
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    closes: List[float] = []
    base = 100.0
    for i in range(n):
        # 微小な上昇 + 浅い周期ノイズ (sin 派生)
        wave = 0.3 * ((i % 20) - 10) / 10.0  # ±0.3%
        closes.append(base * (1 + (daily_drift + wave) / 100.0) ** i)
    df = pd.DataFrame(
        {
            "Open": [c * 0.999 for c in closes],
            "High": [c * 1.005 for c in closes],
            "Low": [c * 0.995 for c in closes],
            "Close": closes,
            "Volume": [1_000_000] * n,
        },
        index=dates,
    )
    return df


def _make_downtrend_df(n: int = 260) -> pd.DataFrame:
    """単調な下降トレンド (require_uptrend を弾けることの確認用)。"""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    closes = [100.0 * (1 - 0.001) ** i for i in range(n)]  # 日次 -0.1%
    return pd.DataFrame(
        {
            "Open": closes, "High": closes, "Low": closes,
            "Close": closes, "Volume": [1_000_000] * n,
        },
        index=dates,
    )


def _entry(ticker: str, name: str = "Test ETF", category: str = "us_index") -> Dict[str, object]:
    return {"ticker": ticker, "name": name, "category": category, "aliases": []}


# ── load_funds_universe / _filter_by_category ────────────────────────────────


class TestUniverseLoading:
    def test_load_funds_universe_returns_list(self):
        funds = load_funds_universe()
        assert isinstance(funds, list)
        assert len(funds) >= 5
        # ticker は必ず含まれる
        assert all("ticker" in f for f in funds)

    def test_universe_includes_voo(self):
        funds = load_funds_universe()
        tickers = [f["ticker"] for f in funds]
        assert "VOO" in tickers

    def test_filter_by_category_all_returns_all(self):
        funds = [_entry("A", category="us_index"), _entry("B", category="global")]
        assert _filter_by_category(funds, "all") == funds

    def test_filter_by_category_specific(self):
        funds = [_entry("A", category="us_index"), _entry("B", category="global")]
        result = _filter_by_category(funds, "us_index")
        assert len(result) == 1
        assert result[0]["ticker"] == "A"

    def test_filter_is_case_insensitive(self):
        funds = [_entry("A", category="us_index")]
        assert _filter_by_category(funds, "US_INDEX") == funds


# ── _score_fund ──────────────────────────────────────────────────────────────


class TestScoreFund:
    def _default_req(self, **kwargs) -> FundRecommendRequest:
        defaults = dict(category="all", top_n=5, horizon="1y", require_uptrend=False)
        defaults.update(kwargs)
        return FundRecommendRequest(**defaults)

    def test_uptrend_returns_candidate_with_positive_score(self):
        df = _make_uptrend_df()
        req = self._default_req()
        cand = _score_fund(_entry("VOO"), df, req)
        assert cand is not None
        assert isinstance(cand, FundCandidate)
        assert cand.score > 0
        assert cand.ticker == "VOO"

    def test_uptrend_has_rationale_text(self):
        df = _make_uptrend_df()
        req = self._default_req()
        cand = _score_fund(_entry("VOO"), df, req)
        assert cand is not None
        assert len(cand.rationale) > 0

    def test_returns_none_when_data_too_short(self):
        df = _make_uptrend_df(n=30)  # 60バー未満
        req = self._default_req()
        cand = _score_fund(_entry("VOO"), df, req)
        assert cand is None

    def test_returns_none_when_close_column_missing(self):
        df = pd.DataFrame({"Open": [1, 2, 3], "Volume": [100, 100, 100]})
        cand = _score_fund(_entry("VOO"), df, self._default_req())
        assert cand is None

    def test_require_uptrend_blocks_downtrend(self):
        df = _make_downtrend_df()
        req = self._default_req(require_uptrend=True)
        cand = _score_fund(_entry("BAD"), df, req)
        assert cand is None

    def test_require_uptrend_passes_uptrend(self):
        df = _make_uptrend_df()
        req = self._default_req(require_uptrend=True)
        cand = _score_fund(_entry("GOOD"), df, req)
        # 200本以上の右肩上がりで SMA50 > SMA200 が成立する想定
        assert cand is not None

    def test_returns_horizon_pct_populated(self):
        df = _make_uptrend_df()
        req = self._default_req(horizon="1y")
        cand = _score_fund(_entry("VOO"), df, req)
        assert cand is not None
        assert cand.return_horizon_pct is not None

    def test_volatility_and_drawdown_populated(self):
        df = _make_uptrend_df()
        cand = _score_fund(_entry("VOO"), df, self._default_req())
        assert cand is not None
        # 上昇トレンドでも軽い波があるのでσ・DDは計算可能
        assert cand.volatility_pct is not None
        assert cand.max_drawdown_pct is not None
        assert cand.max_drawdown_pct <= 0  # ドローダウンは負値

    def test_sma_200_computed_when_enough_bars(self):
        df = _make_uptrend_df(n=260)
        cand = _score_fund(_entry("VOO"), df, self._default_req())
        assert cand is not None
        assert cand.sma_200 is not None
        assert cand.above_sma_200 is True

    def test_score_within_reasonable_bounds(self):
        df = _make_uptrend_df()
        cand = _score_fund(_entry("VOO"), df, self._default_req())
        assert cand is not None
        # 各カテゴリの最大: 35 + 15 + 25 + 15 + 10 = 100
        assert 0 < cand.score <= 100


# ── FundRecommendRequest バリデーション ──────────────────────────────────────


class TestFundRecommendRequest:
    def test_default_values(self):
        req = FundRecommendRequest()
        assert req.category == "all"
        assert req.horizon == "1y"
        assert req.top_n == 5
        assert req.require_uptrend is False

    def test_top_n_upper_bound(self):
        with pytest.raises(Exception):
            FundRecommendRequest(top_n=21)

    def test_top_n_lower_bound(self):
        with pytest.raises(Exception):
            FundRecommendRequest(top_n=0)


# ── run_fund_recommend ──────────────────────────────────────────────────────


class TestRunFundRecommend:
    @pytest.mark.asyncio
    async def test_returns_ranked_candidates_with_mocked_yfinance(self):
        df = _make_uptrend_df()
        mock_data = {"VOO": df, "VTI": df, "QQQ": df}

        with patch("agents.fund_screener._download_batch", return_value=mock_data):
            req = FundRecommendRequest(category="us_index", top_n=2, horizon="1y")
            result = await run_fund_recommend(req)

        assert isinstance(result, FundRecommendResult)
        assert result.category == "us_index"
        assert result.horizon == "1y"
        assert result.total_scanned == 3
        assert len(result.candidates) <= 2
        # ランクは 1 始まりで連番
        for i, c in enumerate(result.candidates, start=1):
            assert c.rank == i

    @pytest.mark.asyncio
    async def test_results_sorted_descending_by_score(self):
        df = _make_uptrend_df()
        mock_data = {"VOO": df, "VTI": df, "QQQ": df}

        with patch("agents.fund_screener._download_batch", return_value=mock_data):
            req = FundRecommendRequest(category="us_index", top_n=10, horizon="1y")
            result = await run_fund_recommend(req)

        scores = [c.score for c in result.candidates]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_disclaimer_is_always_present(self):
        df = _make_uptrend_df()
        mock_data = {"VOO": df}
        with patch("agents.fund_screener._download_batch", return_value=mock_data):
            req = FundRecommendRequest(category="us_index", top_n=1, horizon="1y")
            result = await run_fund_recommend(req)
        assert "投資勧誘" in result.disclaimer or "情報提供" in result.disclaimer

    @pytest.mark.asyncio
    async def test_empty_universe_returns_empty_result(self):
        # 存在しないカテゴリ -> universe が空
        with patch("agents.fund_screener._download_batch", return_value={}):
            req = FundRecommendRequest(
                category="nonexistent_category_xyz", top_n=5, horizon="1y"
            )
            result = await run_fund_recommend(req)
        assert result.total_scanned == 0
        assert result.candidates == []

    @pytest.mark.asyncio
    async def test_skips_funds_with_malformed_data(self):
        good = _make_uptrend_df()
        bad = pd.DataFrame({"Close": [1.0], "Volume": [100]})  # データ不足

        with patch(
            "agents.fund_screener._download_batch",
            return_value={"VOO": good, "BROKEN": bad},
        ):
            req = FundRecommendRequest(category="us_index", top_n=10, horizon="1y")
            result = await run_fund_recommend(req)

        tickers = {c.ticker for c in result.candidates}
        assert "BROKEN" not in tickers


# ── /api/funds/recommend エンドポイント ──────────────────────────────────────


class TestFundsEndpoint:
    @pytest.fixture(autouse=True)
    def _env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APP_ENV", "local")
        monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.setenv("CHARTS_DIR", str(tmp_path / "charts"))
        monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
        monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
        monkeypatch.setenv("DICTIONARIES_DIR", str(tmp_path / "dictionaries"))
        monkeypatch.setenv("ANALYTICS_DATA_DIR", str(tmp_path / "analytics"))

    @pytest.mark.asyncio
    async def test_recommend_endpoint_returns_200(self):
        from httpx import ASGITransport, AsyncClient
        import importlib
        import config
        importlib.reload(config)
        import instrumentation
        instrumentation.setup_observability()  # ASGITransport は lifespan を起動しない
        from main import app

        df = _make_uptrend_df()
        mock_data = {"VOO": df, "VTI": df}

        try:
            with patch("agents.fund_screener._download_batch", return_value=mock_data):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/funds/recommend",
                        json={"category": "us_index", "top_n": 2, "horizon": "1y"},
                    )
        finally:
            await instrumentation.shutdown_observability()

        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "us_index"
        assert data["horizon"] == "1y"
        assert "candidates" in data
        assert "disclaimer" in data
        assert isinstance(data["candidates"], list)

    @pytest.mark.asyncio
    async def test_recommend_endpoint_validates_top_n(self):
        from httpx import ASGITransport, AsyncClient
        import importlib
        import config
        importlib.reload(config)
        import instrumentation
        instrumentation.setup_observability()
        from main import app

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/funds/recommend",
                    json={"category": "us_index", "top_n": 999, "horizon": "1y"},
                )
        finally:
            await instrumentation.shutdown_observability()

        assert resp.status_code == 422
