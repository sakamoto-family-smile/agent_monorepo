"""Tests for the universe loader and Finnhub client."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agents.universe import (
    FinnhubClient,
    get_universe,
    load_json_universe,
)


# ── load_json_universe ───────────────────────────────────────────────────────

class TestLoadJsonUniverse:
    def test_jp_loads_tickers(self):
        tickers = load_json_universe("JP")
        assert len(tickers) > 0
        assert all(t.endswith(".T") for t in tickers)

    def test_us_loads_tickers(self):
        tickers = load_json_universe("US")
        assert len(tickers) > 0
        assert all(not t.endswith(".T") for t in tickers)
        assert "AAPL" in tickers

    def test_growth_loads_mixed_market_tickers(self):
        tickers = load_json_universe("GROWTH")
        assert len(tickers) > 0
        jp_count = sum(1 for t in tickers if t.endswith(".T"))
        us_count = len(tickers) - jp_count
        # 高変動ユニバースはNASDAQと東証グロース両方を含む
        assert jp_count > 0
        assert us_count > 0

    def test_lowercase_market_also_works(self):
        upper = load_json_universe("JP")
        lower = load_json_universe("jp")
        assert upper == lower

    def test_missing_market_returns_empty(self):
        assert load_json_universe("NOPE") == []

    def test_returns_list_of_strings(self):
        for mkt in ("JP", "US", "GROWTH"):
            tickers = load_json_universe(mkt)
            assert all(isinstance(t, str) for t in tickers)

    def test_malformed_json_returns_empty(self, tmp_path, monkeypatch):
        bad_dir = tmp_path / "universe"
        bad_dir.mkdir()
        (bad_dir / "xx.json").write_text("{not valid json}")
        monkeypatch.setattr("agents.universe._UNIVERSE_DIR", bad_dir)
        assert load_json_universe("XX") == []


# ── FinnhubClient ────────────────────────────────────────────────────────────

class TestFinnhubClient:
    def test_available_true_when_key_set(self):
        client = FinnhubClient(api_key="dummy")
        assert client.available is True

    def test_available_false_when_key_empty(self):
        client = FinnhubClient(api_key="")
        assert client.available is False

    def test_reads_key_from_env(self, monkeypatch):
        monkeypatch.setenv("FINNHUB_API_KEY", "env-key")
        client = FinnhubClient()
        assert client.api_key == "env-key"

    def test_fetch_raises_when_no_key(self):
        client = FinnhubClient(api_key="")
        with pytest.raises(RuntimeError, match="FINNHUB_API_KEY"):
            client.fetch_nasdaq_symbols()

    def test_fetch_filters_to_common_stocks(self):
        mock_payload = [
            {"symbol": "AAPL", "type": "Common Stock"},
            {"symbol": "MSFT", "type": "Common Stock"},
            {"symbol": "WARRANT", "type": "Warrant"},
            {"symbol": "BRK.A", "type": "Common Stock"},  # ドット付き → 除外
            {"symbol": "", "type": "Common Stock"},       # 空文字 → 除外
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_payload
        mock_resp.raise_for_status.return_value = None

        with patch("agents.universe.httpx.get", return_value=mock_resp):
            client = FinnhubClient(api_key="dummy")
            symbols = client.fetch_nasdaq_symbols(limit=10)

        assert symbols == ["AAPL", "MSFT"]

    def test_fetch_respects_limit(self):
        mock_payload = [
            {"symbol": f"SYM{i}", "type": "Common Stock"} for i in range(50)
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_payload
        mock_resp.raise_for_status.return_value = None

        with patch("agents.universe.httpx.get", return_value=mock_resp):
            client = FinnhubClient(api_key="dummy")
            symbols = client.fetch_nasdaq_symbols(limit=5)

        assert len(symbols) == 5

    def test_fetch_wraps_http_errors(self):
        def _raise(*args, **kwargs):
            raise httpx.ConnectError("no route")

        with patch("agents.universe.httpx.get", side_effect=_raise):
            client = FinnhubClient(api_key="dummy")
            with pytest.raises(RuntimeError, match="Finnhub request failed"):
                client.fetch_nasdaq_symbols()

    def test_fetch_wraps_non_list_payload(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": "rate limit"}
        mock_resp.raise_for_status.return_value = None

        with patch("agents.universe.httpx.get", return_value=mock_resp):
            client = FinnhubClient(api_key="dummy")
            with pytest.raises(RuntimeError, match="Unexpected Finnhub payload"):
                client.fetch_nasdaq_symbols()


# ── get_universe（JSON + Finnhub 統合） ──────────────────────────────────────

class TestGetUniverse:
    def test_jp_returns_json_only_without_finnhub_call(self):
        """JPマーケットはFinnhubを呼ばずJSONのみを返す。"""
        client = FinnhubClient(api_key="dummy")
        client.fetch_nasdaq_symbols = MagicMock()  # type: ignore[method-assign]

        result = get_universe("JP", finnhub_client=client)

        assert len(result) > 0
        assert all(t.endswith(".T") for t in result)
        client.fetch_nasdaq_symbols.assert_not_called()

    def test_growth_returns_json_only_without_finnhub_call(self):
        client = FinnhubClient(api_key="dummy")
        client.fetch_nasdaq_symbols = MagicMock()  # type: ignore[method-assign]

        result = get_universe("GROWTH", finnhub_client=client)

        assert len(result) > 0
        client.fetch_nasdaq_symbols.assert_not_called()

    def test_all_combines_three_markets(self):
        result = get_universe("ALL")
        jp = load_json_universe("JP")
        us = load_json_universe("US")
        growth = load_json_universe("GROWTH")
        assert len(result) == len(jp) + len(us) + len(growth)

    def test_us_without_api_key_falls_back_to_json(self, monkeypatch):
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
        result = get_universe("US")
        # JSON のみ
        json_us = load_json_universe("US")
        assert result == json_us

    def test_us_with_finnhub_merges_json_and_api(self):
        client = FinnhubClient(api_key="dummy")
        client.fetch_nasdaq_symbols = MagicMock(
            return_value=["NEW1", "NEW2", "AAPL"]  # AAPLはJSON側と重複
        )  # type: ignore[method-assign]

        result = get_universe("US", finnhub_client=client)

        # JSON のティッカーがすべて含まれる
        json_us = load_json_universe("US")
        for t in json_us:
            assert t in result
        # Finnhub の新規ティッカーが追加される
        assert "NEW1" in result
        assert "NEW2" in result
        # 重複は排除される
        assert result.count("AAPL") == 1

    def test_us_with_finnhub_error_falls_back_to_json(self):
        client = FinnhubClient(api_key="dummy")
        client.fetch_nasdaq_symbols = MagicMock(
            side_effect=RuntimeError("rate limit")
        )  # type: ignore[method-assign]

        result = get_universe("US", finnhub_client=client)

        json_us = load_json_universe("US")
        assert result == json_us

    def test_unknown_market_defaults_to_jp(self):
        result = get_universe("MARS")
        json_jp = load_json_universe("JP")
        assert result == json_jp

    def test_ordering_preserves_json_first(self):
        """JSON の銘柄が Finnhub 銘柄より前に並ぶことを確認（キュレーション優先）。"""
        client = FinnhubClient(api_key="dummy")
        client.fetch_nasdaq_symbols = MagicMock(return_value=["ZZZ_FIRST"])  # type: ignore[method-assign]

        result = get_universe("US", finnhub_client=client)

        json_us = load_json_universe("US")
        # JSONの最初のティッカーがresultの最初に来る
        assert result[0] == json_us[0]
        # Finnhub追加分は末尾
        assert result[-1] == "ZZZ_FIRST"
