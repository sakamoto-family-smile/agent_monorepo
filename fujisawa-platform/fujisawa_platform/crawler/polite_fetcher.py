"""礼儀正しい HTTP fetcher。

藤沢市 HP は robots.txt が不在 (404) のため、明示的な許可表明はない。
礼儀ルール (proposal 0003 §3.2) として以下を強制する:

  - User-Agent に連絡先 URL を明示
  - 同時接続 1 (内部 lock で直列化)
  - リクエスト間隔 3 秒以上 (デフォルト)
  - If-Modified-Since / Last-Modified による差分取得
  - 5xx は指数バックオフでリトライ、4xx は fail fast

ETL Cloud Run Jobs (proposal 0003 §4.5) はこの fetcher を共通利用する。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import format_datetime, parsedate_to_datetime
from types import TracebackType

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


class PoliteFetcherConfig(BaseModel):
    """fetcher の設定。env 駆動で上書き可能。"""

    model_config = ConfigDict(frozen=True)

    user_agent: str = Field(
        description="必須。連絡先 URL を含めること (例: 'app/0.1 (https://example.com/contact)')",
    )
    min_interval_sec: float = Field(
        default=3.0,
        ge=0.0,
        description="連続 GET リクエスト間の最小間隔 (秒)。藤沢市 HP は 3.0 を default とする。",
    )
    min_interval_sec_head: float = Field(
        default=0.5,
        ge=0.0,
        description=(
            "連続 HEAD リクエスト間の最小間隔 (秒)。 HEAD はボディ転送無しで負荷が"
            "小さいため GET より短く設定可能。 weekly_crawl の差分 crawl で利用。"
        ),
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        description="5xx エラーの最大リトライ回数。max_retries=3 なら初回 + 3 回 = 計 4 回試行。",
    )
    backoff_base_sec: float = Field(
        default=1.0,
        gt=0.0,
        description="指数バックオフの基準秒。1, 2, 4, 8 ... の倍数で待つ。",
    )
    timeout_sec: float = Field(
        default=30.0,
        gt=0.0,
        description="HTTP request 単体のタイムアウト (秒)。",
    )

    @field_validator("user_agent")
    @classmethod
    def _user_agent_required(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("user_agent must be non-empty")
        return v


class _RetryableError(Exception):
    """tenacity がリトライ判定するための内部マーカー。"""


@dataclass(frozen=True)
class FetchResult:
    """200 OK で取得できた本文。"""

    url: HttpUrl
    status_code: int
    text: str
    last_modified: datetime | None
    etag: str | None


@dataclass(frozen=True)
class NotModified:
    """304 Not Modified を受けた場合の結果。consumer は cache を返す。"""

    url: HttpUrl


@dataclass(frozen=True)
class HeadResult:
    """HEAD request の結果。 weekly_crawl の差分判定用。"""

    url: HttpUrl
    status_code: int
    last_modified: datetime | None
    etag: str | None


class PoliteFetcher:
    """`async with` で使う礼儀正しい fetcher。

    Example:
        config = PoliteFetcherConfig(user_agent="my-app/0.1 (https://example.com)")
        async with PoliteFetcher(config) as fetcher:
            result = await fetcher.fetch("https://www.city.fujisawa.kanagawa.jp/")
    """

    def __init__(self, config: PoliteFetcherConfig) -> None:
        self._config = config
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()  # 同時接続 1
        self._last_fetch_at: float | None = None  # 直前の GET (monotonic 秒)
        self._last_head_at: float | None = None  # 直前の HEAD (monotonic 秒)

    async def __aenter__(self) -> PoliteFetcher:
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

    async def fetch(
        self,
        url: str,
        *,
        if_modified_since: datetime | None = None,
        if_none_match: str | None = None,
    ) -> FetchResult | NotModified:
        """1 URL を fetch。

        Args:
            url: 取得対象 URL。
            if_modified_since: 前回取得時の Last-Modified (UTC datetime)。
                指定すると If-Modified-Since ヘッダを送る。304 が返れば NotModified。
            if_none_match: 前回取得時の ETag。指定すると If-None-Match ヘッダを送る。

        Returns:
            FetchResult (200) または NotModified (304)。

        Raises:
            httpx.HTTPStatusError: 4xx または 5xx (max_retries 後) の場合。
        """
        if self._client is None:
            raise RuntimeError("PoliteFetcher must be used as async context manager")

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
                        return await self._do_fetch(url, if_modified_since, if_none_match)
            except RetryError as err:
                cause = err.last_attempt.exception()
                if isinstance(cause, _RetryableError) and cause.__cause__ is not None:
                    raise cause.__cause__
                raise
            finally:
                self._last_fetch_at = time.monotonic()
            raise RuntimeError("unreachable")  # pragma: no cover

    async def head(self, url: str) -> HeadResult:
        """1 URL に HEAD を打って Last-Modified / ETag を取得する。

        本文を転送しないので polite rate は GET より短い `min_interval_sec_head`
        を別途使う。 5xx は GET と同じく指数バックオフでリトライし、 4xx は
        即 raise する。

        Returns:
            `HeadResult` (status_code は 200 が通常、 但し 304 は HEAD では
            意味を持たないため `If-Modified-Since` ヘッダは送らない)。
        """
        if self._client is None:
            raise RuntimeError("PoliteFetcher must be used as async context manager")

        async with self._lock:
            await self._wait_interval(self._last_head_at, self._config.min_interval_sec_head)
            try:
                async for attempt in AsyncRetrying(
                    stop=stop_after_attempt(self._config.max_retries + 1),
                    wait=wait_exponential(multiplier=self._config.backoff_base_sec),
                    retry=retry_if_exception_type(_RetryableError),
                    reraise=False,
                ):
                    with attempt:
                        return await self._do_head(url)
            except RetryError as err:
                cause = err.last_attempt.exception()
                if isinstance(cause, _RetryableError) and cause.__cause__ is not None:
                    raise cause.__cause__
                raise
            finally:
                self._last_head_at = time.monotonic()
            raise RuntimeError("unreachable")  # pragma: no cover

    async def _do_head(self, url: str) -> HeadResult:
        assert self._client is not None
        response = await self._client.head(url)
        if 500 <= response.status_code < 600:
            err = httpx.HTTPStatusError(
                f"Server error {response.status_code}",
                request=response.request,
                response=response,
            )
            raise _RetryableError(str(err)) from err
        response.raise_for_status()
        return HeadResult(
            url=HttpUrl(str(response.url)),
            status_code=response.status_code,
            last_modified=_parse_http_date(response.headers.get("last-modified")),
            etag=response.headers.get("etag"),
        )

    async def _wait_interval(
        self, last_at: float | None = None, min_interval: float | None = None
    ) -> None:
        """直前の request から指定 interval 経過していなければ待つ。

        引数省略時は GET 用の値 (`_last_fetch_at` / `min_interval_sec`) を使う。
        """
        ref_at = last_at if last_at is not None else self._last_fetch_at
        ref_interval = (
            min_interval if min_interval is not None else self._config.min_interval_sec
        )
        if ref_at is None:
            return
        elapsed = time.monotonic() - ref_at
        remaining = ref_interval - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)

    async def _do_fetch(
        self,
        url: str,
        if_modified_since: datetime | None,
        if_none_match: str | None,
    ) -> FetchResult | NotModified:
        assert self._client is not None
        headers: dict[str, str] = {}
        if if_modified_since is not None:
            headers["If-Modified-Since"] = format_datetime(
                if_modified_since.astimezone(UTC), usegmt=True
            )
        if if_none_match is not None:
            headers["If-None-Match"] = if_none_match

        response = await self._client.get(url, headers=headers)

        if response.status_code == 304:
            return NotModified(url=HttpUrl(str(response.url)))
        if 500 <= response.status_code < 600:
            err = httpx.HTTPStatusError(
                f"Server error {response.status_code}",
                request=response.request,
                response=response,
            )
            raise _RetryableError(str(err)) from err
        response.raise_for_status()  # 4xx は即時 raise

        return FetchResult(
            url=HttpUrl(str(response.url)),
            status_code=response.status_code,
            text=response.text,
            last_modified=_parse_http_date(response.headers.get("last-modified")),
            etag=response.headers.get("etag"),
        )


def _parse_http_date(value: str | None) -> datetime | None:
    """HTTP-date (RFC 1123) を datetime に。失敗時は None。"""
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
