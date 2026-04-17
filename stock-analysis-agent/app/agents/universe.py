"""
銘柄ユニバースのロードと Finnhub 連携。

- `data/universe/{market}.json` から静的リストを読み込む（一次ソース）
- `FINNHUB_API_KEY` が設定されている場合は Finnhub からシンボルを補完する
- Finnhub 失敗時（APIキー未設定・ネットワークエラー・レート制限等）は
  必ず JSON フォールバックに切り替え、呼び出し側では例外を投げない
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

# data/universe ディレクトリのパス（リポジトリルート基準で解決）
_UNIVERSE_DIR = Path(__file__).resolve().parents[2] / "data" / "universe"

_VALID_MARKETS = {"JP", "US", "GROWTH", "ALL"}


def _universe_path(market: str) -> Path:
    return _UNIVERSE_DIR / f"{market.lower()}.json"


def load_json_universe(market: str) -> List[str]:
    """
    単一マーケットのJSONを読み込み、ティッカー文字列のリストを返す。
    ファイル不在・パース失敗時は空リストを返す（呼び出し側で例外を受けない）。
    """
    path = _universe_path(market)
    if not path.exists():
        logger.warning("Universe JSON not found: %s", path)
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to read %s: %s", path, e)
        return []

    tickers = data.get("tickers", [])
    result: List[str] = []
    for entry in tickers:
        if isinstance(entry, dict) and "ticker" in entry:
            result.append(entry["ticker"])
        elif isinstance(entry, str):
            result.append(entry)
    return result


class FinnhubClient:
    """
    Finnhub REST API の薄いクライアント。
    API キーは環境変数 `FINNHUB_API_KEY` から取得する。
    """

    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("FINNHUB_API_KEY", "")
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def fetch_nasdaq_symbols(self, limit: int = 100) -> List[str]:
        """
        NASDAQ上場の普通株シンボルを返す（高変動銘柄の母集団として利用）。
        API キー未設定・HTTP エラー・パース失敗はすべて RuntimeError にラップする。
        """
        if not self.available:
            raise RuntimeError("FINNHUB_API_KEY is not set")

        url = f"{self.BASE_URL}/stock/symbol"
        params = {"exchange": "US", "mic": "XNAS", "token": self.api_key}

        try:
            resp = httpx.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            items = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise RuntimeError(f"Finnhub request failed: {e}") from e

        if not isinstance(items, list):
            raise RuntimeError(f"Unexpected Finnhub payload: {type(items).__name__}")

        symbols: List[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "Common Stock":
                continue
            symbol = item.get("symbol", "")
            # ドット付きシンボル（BRK.A 等）はyfinance互換性が悪いので除外
            if not symbol or "." in symbol:
                continue
            symbols.append(symbol)

        return symbols[:limit]


def get_universe(
    market: str,
    *,
    finnhub_client: Optional[FinnhubClient] = None,
    finnhub_limit: int = 100,
) -> List[str]:
    """
    指定マーケットのユニバースを解決する。

    market:
      - "JP": 日本株（JSON のみ）
      - "US": 米国大型株（JSON + 任意で Finnhub NASDAQ シンボルをマージ）
      - "GROWTH": 高変動・成長期待銘柄（JSON のみ）
      - "ALL": JP + US + GROWTH を結合（Finnhub 失敗時も JSON のみで返る）

    Finnhub 連携:
      - `FINNHUB_API_KEY` 未設定 → JSON のみ
      - API エラー/タイムアウト → ログ出力の上 JSON のみ
      - 成功 → JSON（キュレーション済み）を優先し、Finnhub の新規シンボルを末尾にマージ

    呼び出し側は常に List[str] を受け取り、例外は発生しない。
    """
    market_u = market.upper()
    if market_u not in _VALID_MARKETS:
        logger.warning("Unknown market %s, defaulting to JP", market_u)
        market_u = "JP"

    if market_u == "ALL":
        return (
            load_json_universe("JP")
            + load_json_universe("US")
            + load_json_universe("GROWTH")
        )

    json_tickers = load_json_universe(market_u)

    # Finnhub 補完は US のみ対象（NASDAQ）
    if market_u != "US":
        return json_tickers

    client = finnhub_client if finnhub_client is not None else FinnhubClient()
    if not client.available:
        logger.info("Finnhub API key not set; using JSON universe only")
        return json_tickers

    try:
        finnhub_tickers = client.fetch_nasdaq_symbols(limit=finnhub_limit)
    except Exception as e:  # noqa: BLE001 — 意図的に全例外を JSON フォールバック
        logger.warning("Finnhub fetch failed, falling back to JSON: %s", e)
        return json_tickers

    # 重複を除いて JSON 優先でマージ
    merged = list(dict.fromkeys(json_tickers + finnhub_tickers))
    logger.info(
        "Universe resolved: json=%d, finnhub=%d, merged=%d",
        len(json_tickers),
        len(finnhub_tickers),
        len(merged),
    )
    return merged
