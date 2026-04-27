"""e-Gov 法令検索 API v2 の薄いクライアント。

設計:
- DESIGN.md §2.1 / DATA_SOURCES.md §1 に基づき道路交通法・施行令等の条文を取得
- security-platform proxy を経由（DESIGN.md §15.2）
- Phase 2-F は **条文単位の生テキスト取得のみ**。スキーマ正規化は Phase 4 で
  law-update-pipeline に移管

利用条件: 政府標準利用規約 第 2.0 版（CC BY 4.0 互換）。商用可、出典必須。
出典フォーマットは `app.handlers.disclaimer` 側で組み立てる想定。

API ドキュメント:
- Swagger UI: https://laws.e-gov.go.jp/api/2/swagger-ui
- 仕様確定 (Phase 0 確認): JSON simplified response が 2026-03-15 に追加
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.integrations.proxied_http_client import (
    DEFAULT_TIMEOUT_SECONDS,
    build_proxied_async_client,
)

logger = logging.getLogger(__name__)


# e-Gov 法令検索 API v2 のベース URL。
DEFAULT_EGOV_BASE_URL = "https://laws.e-gov.go.jp/api/2"


class EgovLawError(Exception):
    """e-Gov API 呼び出しの汎用エラー。"""


@dataclass(frozen=True)
class LawArticleSnapshot:
    """1 条文の最小スナップショット。"""

    law_id: str
    article: str  # "36" や "36-2" のような identifier
    quoted_text: str  # 条文本文（要点の生テキスト、URL アンカー付与用）
    url: str  # e-Gov 上の条文単位アンカー付き URL
    fetched_at_iso: str = ""


class EgovLawClient:
    """e-Gov 法令検索 API のクライアント。

    本クラスは Phase 2-F 時点では「単純な fetch」のみ提供。Phase 4 で
    law-update-pipeline が e-Gov の差分を BigQuery に取り込んで構造化する
    までの繋ぎ。
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_EGOV_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        # client が DI されている場合（テスト等）は持ち回し、close は呼ばない
        self._injected_client = client

    async def fetch_law_text(self, law_id: str) -> str:
        """法令 ID（例: "335AC0000000105" = 道路交通法）の本文 XML/JSON を返す。

        戻り値はテキストそのまま。スキーマ解釈は呼び出し側で行う。
        """
        url = f"{self._base_url}/law_data/{law_id}"
        async with self._maybe_injected_client() as client:
            try:
                resp = await client.get(url)
            except httpx.HTTPError as exc:
                raise EgovLawError(f"e-Gov fetch failed for {law_id}: {exc}") from exc
        if resp.status_code != 200:
            raise EgovLawError(
                f"e-Gov returned status={resp.status_code} for {law_id}"
            )
        return resp.text

    async def health_check(self) -> bool:
        """API ベースが到達可能かのスモークチェック。

        本番運用では Cloud Monitoring の uptime check を使う。本メソッドは
        local / CI から手動検証用。
        """
        async with self._maybe_injected_client() as client:
            try:
                resp = await client.get(f"{self._base_url}/swagger.json", timeout=5.0)
            except httpx.HTTPError as exc:
                logger.warning("e-Gov health_check failed: %s", exc)
                return False
        return resp.status_code < 500

    def _maybe_injected_client(self) -> httpx.AsyncClient:
        if self._injected_client is not None:
            return _ContextWrapper(self._injected_client)  # type: ignore[return-value]
        return build_proxied_async_client(timeout=self._timeout)


class _ContextWrapper:
    """DI された client を `async with` で包み込み、本クラス側では close しない。"""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, *args: object) -> None:
        return None


__all__ = [
    "DEFAULT_EGOV_BASE_URL",
    "EgovLawClient",
    "EgovLawError",
    "LawArticleSnapshot",
]
