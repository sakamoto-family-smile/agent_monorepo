"""PoliteFetcher のテスト。

検証項目 (proposal 0003 §3.2 の礼儀ルール):
- User-Agent 明示 (連絡先 URL 含む)
- 同時接続 1 (内部 lock で直列化)
- リクエスト間隔 3 秒以上 (デフォルト)
- If-Modified-Since 自動付与 + 304 Not Modified の handling
- 5xx は指数バックオフでリトライ、4xx は fail fast
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import httpx
import pytest
import respx

from fujisawa_platform.crawler.polite_fetcher import (
    FetchResult,
    NotModified,
    PoliteFetcher,
    PoliteFetcherConfig,
)


@pytest.fixture
def config() -> PoliteFetcherConfig:
    """テスト用 config。間隔を短くしてテスト時間を抑える。"""
    return PoliteFetcherConfig(
        user_agent="fujisawa-platform-test/0.1 (https://example.com/contact)",
        min_interval_sec=0.05,  # 50ms (本番は 3s)
        max_retries=3,
        backoff_base_sec=0.01,  # 10ms (本番は 1s+)
    )


class TestUserAgent:
    @pytest.mark.asyncio
    @respx.mock
    async def test_sets_configured_user_agent(self, config: PoliteFetcherConfig) -> None:
        """設定された UA が常にヘッダに付く。"""
        route = respx.get("https://www.city.fujisawa.kanagawa.jp/").mock(
            return_value=httpx.Response(200, text="ok"),
        )
        async with PoliteFetcher(config) as fetcher:
            await fetcher.fetch("https://www.city.fujisawa.kanagawa.jp/")
        assert route.called
        sent_ua = route.calls.last.request.headers.get("user-agent")
        assert sent_ua == config.user_agent
        assert "https://example.com/contact" in sent_ua


class TestIntervalThrottling:
    @pytest.mark.asyncio
    @respx.mock
    async def test_enforces_minimum_interval_between_requests(
        self, config: PoliteFetcherConfig
    ) -> None:
        """連続呼出は min_interval_sec 以上の間隔が空く。"""
        respx.get("https://www.city.fujisawa.kanagawa.jp/a").mock(
            return_value=httpx.Response(200, text="A"),
        )
        respx.get("https://www.city.fujisawa.kanagawa.jp/b").mock(
            return_value=httpx.Response(200, text="B"),
        )

        async with PoliteFetcher(config) as fetcher:
            t0 = time.monotonic()
            await fetcher.fetch("https://www.city.fujisawa.kanagawa.jp/a")
            await fetcher.fetch("https://www.city.fujisawa.kanagawa.jp/b")
            elapsed = time.monotonic() - t0

        # 2 回目は 50ms 待ってから発行されるはず
        assert elapsed >= config.min_interval_sec * 0.9  # 計時誤差 10% 許容

    @pytest.mark.asyncio
    @respx.mock
    async def test_serializes_concurrent_requests(self, config: PoliteFetcherConfig) -> None:
        """同時に gather しても直列化されて間隔が空く (= 同時接続 1)。"""
        respx.get(url__regex=r"https://www\.city\.fujisawa\.kanagawa\.jp/\d").mock(
            return_value=httpx.Response(200, text="ok"),
        )

        async with PoliteFetcher(config) as fetcher:
            t0 = time.monotonic()
            await asyncio.gather(
                fetcher.fetch("https://www.city.fujisawa.kanagawa.jp/1"),
                fetcher.fetch("https://www.city.fujisawa.kanagawa.jp/2"),
                fetcher.fetch("https://www.city.fujisawa.kanagawa.jp/3"),
            )
            elapsed = time.monotonic() - t0

        # 3 fetch の最低時間 = 2 * min_interval (1 個目は即時、2/3 個目は待機)
        assert elapsed >= config.min_interval_sec * 1.8


class TestIfModifiedSince:
    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_if_modified_since_when_provided(
        self, config: PoliteFetcherConfig
    ) -> None:
        """last_modified を指定すると If-Modified-Since ヘッダが付く。"""
        route = respx.get("https://www.city.fujisawa.kanagawa.jp/").mock(
            return_value=httpx.Response(200, text="ok"),
        )
        last_modified = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)

        async with PoliteFetcher(config) as fetcher:
            await fetcher.fetch(
                "https://www.city.fujisawa.kanagawa.jp/",
                if_modified_since=last_modified,
            )

        sent_ifms = route.calls.last.request.headers.get("if-modified-since")
        # RFC 1123 形式: "Fri, 01 May 2026 12:00:00 GMT"
        assert sent_ifms is not None
        assert "01 May 2026" in sent_ifms
        assert "GMT" in sent_ifms

    @pytest.mark.asyncio
    @respx.mock
    async def test_304_returns_not_modified_marker(
        self, config: PoliteFetcherConfig
    ) -> None:
        """304 Not Modified は NotModified を返す (例外ではなく値)。"""
        respx.get("https://www.city.fujisawa.kanagawa.jp/").mock(
            return_value=httpx.Response(304),
        )

        async with PoliteFetcher(config) as fetcher:
            result = await fetcher.fetch(
                "https://www.city.fujisawa.kanagawa.jp/",
                if_modified_since=datetime(2026, 1, 1, tzinfo=UTC),
            )

        assert isinstance(result, NotModified)


class TestRetry:
    @pytest.mark.asyncio
    @respx.mock
    async def test_retries_on_5xx(self, config: PoliteFetcherConfig) -> None:
        """5xx は指数バックオフでリトライし、最終的に成功すれば返す。"""
        route = respx.get("https://www.city.fujisawa.kanagawa.jp/")
        route.side_effect = [
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(200, text="recovered"),
        ]

        async with PoliteFetcher(config) as fetcher:
            result = await fetcher.fetch("https://www.city.fujisawa.kanagawa.jp/")

        assert isinstance(result, FetchResult)
        assert result.text == "recovered"
        assert route.call_count == 3

    @pytest.mark.asyncio
    @respx.mock
    async def test_does_not_retry_on_4xx(self, config: PoliteFetcherConfig) -> None:
        """4xx は fail fast。HTTPStatusError を上げる。"""
        route = respx.get("https://www.city.fujisawa.kanagawa.jp/").mock(
            return_value=httpx.Response(404),
        )

        async with PoliteFetcher(config) as fetcher:
            with pytest.raises(httpx.HTTPStatusError):
                await fetcher.fetch("https://www.city.fujisawa.kanagawa.jp/")

        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_gives_up_after_max_retries(self, config: PoliteFetcherConfig) -> None:
        """5xx が連続したら max_retries 回で諦める。"""
        route = respx.get("https://www.city.fujisawa.kanagawa.jp/").mock(
            return_value=httpx.Response(503),
        )

        async with PoliteFetcher(config) as fetcher:
            with pytest.raises(httpx.HTTPStatusError):
                await fetcher.fetch("https://www.city.fujisawa.kanagawa.jp/")

        # max_retries=3 → 初回 + リトライ 3 回 = 4 回試行
        assert route.call_count == config.max_retries + 1


class TestFetchResult:
    @pytest.mark.asyncio
    @respx.mock
    async def test_extracts_last_modified_from_response(
        self, config: PoliteFetcherConfig
    ) -> None:
        """レスポンスの Last-Modified ヘッダを FetchResult に詰める。"""
        respx.get("https://www.city.fujisawa.kanagawa.jp/").mock(
            return_value=httpx.Response(
                200,
                text="ok",
                headers={"last-modified": "Wed, 01 Jan 2026 00:00:00 GMT"},
            ),
        )

        async with PoliteFetcher(config) as fetcher:
            result = await fetcher.fetch("https://www.city.fujisawa.kanagawa.jp/")

        assert isinstance(result, FetchResult)
        assert result.last_modified is not None
        assert result.last_modified.year == 2026
        assert result.last_modified.month == 1
        assert result.last_modified.day == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_status_code_and_url(self, config: PoliteFetcherConfig) -> None:
        """FetchResult に status / url / text が含まれる。"""
        respx.get("https://www.city.fujisawa.kanagawa.jp/x").mock(
            return_value=httpx.Response(200, text="hello"),
        )

        async with PoliteFetcher(config) as fetcher:
            result = await fetcher.fetch("https://www.city.fujisawa.kanagawa.jp/x")

        assert isinstance(result, FetchResult)
        assert result.status_code == 200
        assert result.text == "hello"
        assert str(result.url) == "https://www.city.fujisawa.kanagawa.jp/x"


class TestRequiredUserAgent:
    def test_empty_user_agent_rejected(self) -> None:
        """UA 未設定の config は構築段階で弾く (匿名 fetch を防ぐ)。"""
        with pytest.raises(ValueError, match="user_agent"):
            PoliteFetcherConfig(user_agent="")
