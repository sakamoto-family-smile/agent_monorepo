"""Wayback Machine CDX + Web Archive のクライアント。

藤沢市 HP の過去 PDF (令和 4-6 年の年次入所結果 PDF / `r4-4nyuusyonaiteisisuu.pdf` 等) を
Wayback Machine 経由でバックフィルするための薄いクライアント。

実利用は **Phase 4 の `etl/wayback_backfill.py`** で 1 度きり呼ばれる想定 (proposal 0003 §4.5.4
の `wayback_backfill` Job)。本モジュールは parse / fetch のロジックのみを担当する。

設計上の選択 (proposal 0003 §A2 / 調査ノート §A2 由来):
- CDX API (`web.archive.org/cdx/search/cdx`) は 503 を返すことがあるため tenacity で retry
- 礼儀のため `min_interval_sec=5.0` (web.archive.org も負荷をかけない)
- `web.archive.org` は別ホストのため、`PoliteFetcher` (藤沢市向け) は流用しない
- archive URL は `https://web.archive.org/web/{timestamp}/{original_url}` の決定的形式
- CDX クエリの statuscode != 200 行 (404 / 301 等) は捨てる
- 4xx は fail-fast、5xx は max_retries 後に WaybackError
"""

from __future__ import annotations

import asyncio
import time
from types import TracebackType
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

CDX_API_URL = "https://web.archive.org/cdx/search/cdx"
ARCHIVE_BASE = "https://web.archive.org/web"


class WaybackError(RuntimeError):
    """Wayback API / archive 取得に失敗。

    CDX 503 が `max_retries` 連続した場合や、archive 4xx (snapshot 消失) で raise。
    Phase 4 ETL では「5 連敗で fail-fast、再開は手動」(proposal 0003 §A2-4)。
    """


class _RetryableError(Exception):
    """tenacity がリトライ判定するための内部マーカー (5xx 用)。"""


class WaybackConfig(BaseModel):
    """Wayback クライアントの設定。"""

    model_config = ConfigDict(frozen=True)

    user_agent: str = Field(
        description="必須。連絡先 URL を含めること。",
    )
    min_interval_sec: float = Field(
        default=5.0,
        ge=0.0,
        description="連続リクエスト間の最小間隔。web.archive.org への礼儀として 5s default。",
    )
    max_retries: int = Field(
        default=5,
        ge=0,
        description="503 のリトライ回数。max_retries=5 なら計 6 回試行。",
    )
    backoff_base_sec: float = Field(
        default=5.0,
        gt=0.0,
        description="指数バックオフの基準秒。",
    )
    timeout_sec: float = Field(
        default=60.0,
        gt=0.0,
        description="HTTP request 単体のタイムアウト (秒)。CDX は遅い時 30s+ かかる。",
    )

    @field_validator("user_agent")
    @classmethod
    def _user_agent_required(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("user_agent must be non-empty")
        return v


class WaybackSnapshot(BaseModel):
    """CDX が返す 1 行 = 1 スナップショットを表すモデル。"""

    model_config = ConfigDict(frozen=True)

    timestamp: str = Field(description="YYYYMMDDhhmmss 形式の Wayback タイムスタンプ")
    original_url: HttpUrl
    mimetype: str
    status_code: int
    digest: str

    @property
    def archive_url(self) -> str:
        """Web Archive 経由で取得するための URL。"""
        return build_archive_url(self.timestamp, str(self.original_url))


def build_archive_url(timestamp: str, original_url: str) -> str:
    """archive URL を組み立てる。

    Args:
        timestamp: YYYYMMDDhhmmss 形式の Wayback タイムスタンプ。
        original_url: バックアップ元の絶対 URL。

    Returns:
        `https://web.archive.org/web/{timestamp}/{original_url}` 形式の URL。
    """
    if not timestamp:
        raise ValueError("timestamp must be non-empty")
    if not original_url:
        raise ValueError("original_url must be non-empty")
    return f"{ARCHIVE_BASE}/{timestamp}/{original_url}"


class WaybackClient:
    """`async with` で使う Wayback クライアント。

    Example:
        config = WaybackConfig(user_agent="my-app/0.1 (https://example.com)")
        async with WaybackClient(config) as client:
            snapshots = await client.query_cdx(
                "https://www.city.fujisawa.kanagawa.jp/hoiku/documents/r4-4nyuusyonaiteisisuu.pdf",
                from_timestamp="20220101000000",
                mimetype="application/pdf",
            )
            for snap in snapshots:
                pdf_bytes = await client.fetch_archive(snap)
                ...
    """

    def __init__(self, config: WaybackConfig) -> None:
        self._config = config
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._last_fetch_at: float | None = None

    async def __aenter__(self) -> WaybackClient:
        self._client = httpx.AsyncClient(
            headers={"User-Agent": self._config.user_agent},
            timeout=self._config.timeout_sec,
            follow_redirects=True,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def query_cdx(
        self,
        url: str,
        *,
        from_timestamp: str | None = None,
        to_timestamp: str | None = None,
        mimetype: str | None = None,
    ) -> list[WaybackSnapshot]:
        """CDX API でスナップショット一覧を取得する。

        statuscode != 200 のスナップショット (404 / 301 等) は除外する。

        Args:
            url: 元 URL (例: `https://www.city.fujisawa.kanagawa.jp/.../x.pdf`)。
            from_timestamp: YYYYMMDDhhmmss 形式の下限 (含む)。
            to_timestamp: YYYYMMDDhhmmss 形式の上限 (含む)。
            mimetype: フィルタしたい mimetype (例: `application/pdf`)。

        Returns:
            スナップショットのリスト。0 件の場合は空 list。

        Raises:
            WaybackError: 4xx (即時) / 5xx max_retries 超過 / JSON parse 失敗。
        """
        params: dict[str, str] = {"url": url, "output": "json"}
        if from_timestamp:
            params["from"] = from_timestamp
        if to_timestamp:
            params["to"] = to_timestamp
        if mimetype:
            params["filter"] = f"mimetype:{mimetype}"

        rows = await self._get_json_with_retry(CDX_API_URL, params=params)
        return _rows_to_snapshots(rows)

    async def fetch_archive(self, snapshot: WaybackSnapshot) -> bytes:
        """Web Archive から実ファイルを取得する。

        Args:
            snapshot: `query_cdx` で得た WaybackSnapshot。

        Returns:
            生バイト列 (PDF / HTML / etc.)。

        Raises:
            WaybackError: 4xx (snapshot が消失) / 5xx max_retries 超過。
        """
        return await self._get_bytes_with_retry(snapshot.archive_url)

    async def _get_json_with_retry(self, url: str, params: dict[str, str]) -> list[list[str]]:
        response = await self._request_with_retry(url, params=params)
        try:
            data = response.json()
        except ValueError as err:
            raise WaybackError(f"CDX returned non-JSON: {err}") from err
        if not isinstance(data, list):
            raise WaybackError(f"CDX returned unexpected JSON shape: {type(data).__name__}")
        return data

    async def _get_bytes_with_retry(self, url: str) -> bytes:
        response = await self._request_with_retry(url, params=None)
        return response.content

    async def _request_with_retry(
        self,
        url: str,
        *,
        params: dict[str, str] | None,
    ) -> httpx.Response:
        if self._client is None:
            raise RuntimeError("WaybackClient must be used as async context manager")

        async with self._lock:
            await self._wait_interval()
            try:
                async for attempt in AsyncRetrying(
                    stop=stop_after_attempt(self._config.max_retries + 1),
                    wait=wait_exponential(multiplier=self._config.backoff_base_sec),
                    retry=retry_if_exception_type(_RetryableError),
                    reraise=False,
                ):
                    with attempt:
                        return await self._do_request(url, params)
            except RetryError as err:
                cause = err.last_attempt.exception()
                if isinstance(cause, _RetryableError):
                    raise WaybackError(str(cause)) from cause
                raise
            finally:
                self._last_fetch_at = time.monotonic()
            raise RuntimeError("unreachable")  # pragma: no cover

    async def _do_request(self, url: str, params: dict[str, str] | None) -> httpx.Response:
        assert self._client is not None
        response = await self._client.get(url, params=params)
        if 500 <= response.status_code < 600:
            raise _RetryableError(f"server error {response.status_code} on {url}")
        if 400 <= response.status_code < 500:
            raise WaybackError(f"client error {response.status_code} on {url}")
        return response

    async def _wait_interval(self) -> None:
        if self._last_fetch_at is None:
            return
        elapsed = time.monotonic() - self._last_fetch_at
        remaining = self._config.min_interval_sec - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)


def _rows_to_snapshots(rows: list[list[Any]]) -> list[WaybackSnapshot]:
    """CDX JSON 出力の生 rows を WaybackSnapshot に変換 (statuscode != 200 を除外)。

    CDX JSON output spec:
        - 1 行目: ヘッダ行 (列名)。空の結果でもこの行のみ返ってくる。
        - 2 行目以降: データ行。列順は ["urlkey", "timestamp", "original",
          "mimetype", "statuscode", "digest", "length"]。

    完全に空配列 (`[]`) の場合は空 list を返す (CDX が稀にこの形を返す)。
    """
    if not rows:
        return []

    header = rows[0]
    if not _is_header(header):
        # ヘッダ無しでデータ行から始まるケース (theoretical) に念のため対応。
        data_rows = rows
        idx = _DEFAULT_INDEX
    else:
        data_rows = rows[1:]
        idx = _build_index(header)

    snapshots: list[WaybackSnapshot] = []
    for row in data_rows:
        try:
            status_code = int(row[idx["statuscode"]])
        except (ValueError, IndexError, KeyError):
            continue
        if status_code != 200:
            continue
        try:
            snapshots.append(
                WaybackSnapshot(
                    timestamp=row[idx["timestamp"]],
                    original_url=row[idx["original"]],
                    mimetype=row[idx["mimetype"]],
                    status_code=status_code,
                    digest=row[idx["digest"]],
                )
            )
        except (IndexError, KeyError, ValueError) as err:
            raise WaybackError(f"unexpected CDX row shape: {row} ({err})") from err
    return snapshots


_DEFAULT_INDEX: dict[str, int] = {
    "urlkey": 0,
    "timestamp": 1,
    "original": 2,
    "mimetype": 3,
    "statuscode": 4,
    "digest": 5,
    "length": 6,
}


def _is_header(row: list[Any]) -> bool:
    return len(row) >= 5 and row[0] == "urlkey" and row[1] == "timestamp"


def _build_index(header: list[Any]) -> dict[str, int]:
    return {str(name): i for i, name in enumerate(header)}
