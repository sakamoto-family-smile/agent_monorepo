"""wayback module のテスト。

Wayback CDX API + Web Archive の helper を検証する。

仕様の根拠 (proposal 0003 §A2 / 調査ノート §A2):
- CDX API は **5 秒間隔 + 指数バックオフ** で polite に叩く (web.archive.org も負荷をかけない)
- 503 は持続することがある → tenacity の最大 retry 後に WaybackError
- archive URL は `https://web.archive.org/web/{timestamp}/{original_url}` の決定的フォーマット
- 取得対象は `application/pdf` mimetype のみ (令和 4-6 年の年次入所結果 PDF)
- バックフィルは **一度きり** の Phase 4 ETL Job 内で呼ばれる
"""

from __future__ import annotations

import httpx
import pytest
import respx

from fujisawa_platform.crawler.wayback import (
    WaybackClient,
    WaybackConfig,
    WaybackError,
    WaybackSnapshot,
    build_archive_url,
)


@pytest.fixture
def config() -> WaybackConfig:
    """テスト用 config (sleep を限りなくゼロに)。"""
    return WaybackConfig(
        user_agent="fujisawa-platform-test/0.1 (https://example.com/contact)",
        min_interval_sec=0.01,
        max_retries=3,
        backoff_base_sec=0.001,
        timeout_sec=10.0,
    )


# CDX JSON output: 1 行目はヘッダ行、以降がデータ行。
# 列順: urlkey / timestamp / original / mimetype / statuscode / digest / length
_CDX_HEADER = ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"]


def _cdx_row(
    timestamp: str,
    original: str,
    mimetype: str = "application/pdf",
    status: str = "200",
    digest: str = "AAA",
    length: str = "1000",
) -> list[str]:
    return ["urlkey", timestamp, original, mimetype, status, digest, length]


class TestBuildArchiveUrl:
    def test_basic(self) -> None:
        url = build_archive_url(
            "20220308120000",
            "https://www.city.fujisawa.kanagawa.jp/hoiku/documents/r4-4nyuusyonaiteisisuu.pdf",
        )
        assert url == (
            "https://web.archive.org/web/20220308120000/"
            "https://www.city.fujisawa.kanagawa.jp/hoiku/documents/r4-4nyuusyonaiteisisuu.pdf"
        )

    def test_empty_timestamp_rejected(self) -> None:
        with pytest.raises(ValueError, match="timestamp"):
            build_archive_url("", "https://example.com/x.pdf")

    def test_empty_url_rejected(self) -> None:
        with pytest.raises(ValueError, match="original_url"):
            build_archive_url("20220308120000", "")


class TestSnapshotModel:
    def test_archive_url_property(self) -> None:
        s = WaybackSnapshot(
            timestamp="20220308120000",
            original_url="https://www.city.fujisawa.kanagawa.jp/x.pdf",
            mimetype="application/pdf",
            status_code=200,
            digest="AAA",
        )
        assert s.archive_url == (
            "https://web.archive.org/web/20220308120000/https://www.city.fujisawa.kanagawa.jp/x.pdf"
        )

    def test_frozen(self) -> None:
        s = WaybackSnapshot(
            timestamp="20220308120000",
            original_url="https://www.city.fujisawa.kanagawa.jp/x.pdf",
            mimetype="application/pdf",
            status_code=200,
            digest="AAA",
        )
        with pytest.raises(Exception):
            s.timestamp = "20230101000000"  # type: ignore[misc]


class TestQueryCdx:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_snapshots_when_results_exist(self, config: WaybackConfig) -> None:
        rows = [
            _CDX_HEADER,
            _cdx_row("20220308120000", "https://www.city.fujisawa.kanagawa.jp/a.pdf"),
            _cdx_row("20220601090000", "https://www.city.fujisawa.kanagawa.jp/a.pdf"),
        ]
        respx.get("https://web.archive.org/cdx/search/cdx").mock(
            return_value=httpx.Response(200, json=rows),
        )

        async with WaybackClient(config) as client:
            snapshots = await client.query_cdx("https://www.city.fujisawa.kanagawa.jp/a.pdf")

        assert len(snapshots) == 2
        assert snapshots[0].timestamp == "20220308120000"
        assert str(snapshots[0].original_url) == "https://www.city.fujisawa.kanagawa.jp/a.pdf"
        assert snapshots[0].status_code == 200
        assert snapshots[0].mimetype == "application/pdf"

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_result_returns_empty_list(self, config: WaybackConfig) -> None:
        """CDX が結果ゼロのとき (= ヘッダ行のみ) は空 list を返す。"""
        respx.get("https://web.archive.org/cdx/search/cdx").mock(
            return_value=httpx.Response(200, json=[_CDX_HEADER]),
        )
        async with WaybackClient(config) as client:
            snapshots = await client.query_cdx("https://www.city.fujisawa.kanagawa.jp/x.pdf")
        assert snapshots == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_completely_empty_response_returns_empty_list(
        self, config: WaybackConfig
    ) -> None:
        """CDX が完全に空配列 [] (ヘッダすら無い) を返すケースも空 list 扱い。"""
        respx.get("https://web.archive.org/cdx/search/cdx").mock(
            return_value=httpx.Response(200, json=[]),
        )
        async with WaybackClient(config) as client:
            snapshots = await client.query_cdx("https://www.city.fujisawa.kanagawa.jp/x.pdf")
        assert snapshots == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_passes_query_filters(self, config: WaybackConfig) -> None:
        """from_ts / to_ts / mimetype が CDX クエリパラメータに反映される。"""
        route = respx.get("https://web.archive.org/cdx/search/cdx").mock(
            return_value=httpx.Response(200, json=[_CDX_HEADER]),
        )
        async with WaybackClient(config) as client:
            await client.query_cdx(
                "https://www.city.fujisawa.kanagawa.jp/x.pdf",
                from_timestamp="20220101000000",
                to_timestamp="20221231235959",
                mimetype="application/pdf",
            )

        params = route.calls.last.request.url.params
        assert params.get("url") == "https://www.city.fujisawa.kanagawa.jp/x.pdf"
        assert params.get("from") == "20220101000000"
        assert params.get("to") == "20221231235959"
        assert params.get("filter") == "mimetype:application/pdf"
        assert params.get("output") == "json"

    @pytest.mark.asyncio
    @respx.mock
    async def test_503_retried_then_succeeds(self, config: WaybackConfig) -> None:
        """503 → 503 → 200 の順で来たらリトライして最終成功を返す。"""
        route = respx.get("https://web.archive.org/cdx/search/cdx")
        route.side_effect = [
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(
                200,
                json=[
                    _CDX_HEADER,
                    _cdx_row("20220308120000", "https://www.city.fujisawa.kanagawa.jp/a.pdf"),
                ],
            ),
        ]

        async with WaybackClient(config) as client:
            snapshots = await client.query_cdx("https://www.city.fujisawa.kanagawa.jp/a.pdf")

        assert len(snapshots) == 1
        assert route.call_count == 3

    @pytest.mark.asyncio
    @respx.mock
    async def test_503_persistent_raises_wayback_error(self, config: WaybackConfig) -> None:
        """503 が max_retries 連続したら WaybackError を上げる (再開は手動)。"""
        route = respx.get("https://web.archive.org/cdx/search/cdx").mock(
            return_value=httpx.Response(503),
        )
        async with WaybackClient(config) as client:
            with pytest.raises(WaybackError):
                await client.query_cdx("https://www.city.fujisawa.kanagawa.jp/x.pdf")
        assert route.call_count == config.max_retries + 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_4xx_fail_fast(self, config: WaybackConfig) -> None:
        """4xx は retry せずに即時 WaybackError。"""
        route = respx.get("https://web.archive.org/cdx/search/cdx").mock(
            return_value=httpx.Response(400),
        )
        async with WaybackClient(config) as client:
            with pytest.raises(WaybackError):
                await client.query_cdx("https://www.city.fujisawa.kanagawa.jp/x.pdf")
        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_skips_non_200_status_rows(self, config: WaybackConfig) -> None:
        """CDX の statuscode が 200 でない行 (404 / 301 など) は除外する。

        Wayback には 404 のスナップショットも履歴として残るが、PDF としては取得不可。
        """
        rows = [
            _CDX_HEADER,
            _cdx_row("20220308120000", "https://x.com/a.pdf", status="404"),
            _cdx_row("20220601090000", "https://x.com/a.pdf", status="200"),
            _cdx_row("20221201090000", "https://x.com/a.pdf", status="301"),
        ]
        respx.get("https://web.archive.org/cdx/search/cdx").mock(
            return_value=httpx.Response(200, json=rows),
        )
        async with WaybackClient(config) as client:
            snapshots = await client.query_cdx("https://x.com/a.pdf")

        assert len(snapshots) == 1
        assert snapshots[0].status_code == 200
        assert snapshots[0].timestamp == "20220601090000"


class TestFetchArchive:
    @pytest.mark.asyncio
    @respx.mock
    async def test_fetches_archive_bytes(self, config: WaybackConfig) -> None:
        snapshot = WaybackSnapshot(
            timestamp="20220308120000",
            original_url="https://www.city.fujisawa.kanagawa.jp/a.pdf",
            mimetype="application/pdf",
            status_code=200,
            digest="AAA",
        )
        respx.get(snapshot.archive_url).mock(
            return_value=httpx.Response(200, content=b"%PDF-1.4 fake"),
        )
        async with WaybackClient(config) as client:
            content = await client.fetch_archive(snapshot)
        assert content == b"%PDF-1.4 fake"

    @pytest.mark.asyncio
    @respx.mock
    async def test_503_retried_then_succeeds(self, config: WaybackConfig) -> None:
        snapshot = WaybackSnapshot(
            timestamp="20220308120000",
            original_url="https://www.city.fujisawa.kanagawa.jp/a.pdf",
            mimetype="application/pdf",
            status_code=200,
            digest="AAA",
        )
        route = respx.get(snapshot.archive_url)
        route.side_effect = [
            httpx.Response(503),
            httpx.Response(200, content=b"%PDF-1.4 ok"),
        ]
        async with WaybackClient(config) as client:
            content = await client.fetch_archive(snapshot)
        assert content == b"%PDF-1.4 ok"

    @pytest.mark.asyncio
    @respx.mock
    async def test_404_fails_fast(self, config: WaybackConfig) -> None:
        snapshot = WaybackSnapshot(
            timestamp="20220308120000",
            original_url="https://www.city.fujisawa.kanagawa.jp/missing.pdf",
            mimetype="application/pdf",
            status_code=200,
            digest="AAA",
        )
        respx.get(snapshot.archive_url).mock(return_value=httpx.Response(404))
        async with WaybackClient(config) as client:
            with pytest.raises(WaybackError):
                await client.fetch_archive(snapshot)


class TestUserAgent:
    @pytest.mark.asyncio
    @respx.mock
    async def test_user_agent_header_set(self, config: WaybackConfig) -> None:
        route = respx.get("https://web.archive.org/cdx/search/cdx").mock(
            return_value=httpx.Response(200, json=[_CDX_HEADER]),
        )
        async with WaybackClient(config) as client:
            await client.query_cdx("https://x.com/a.pdf")
        sent_ua = route.calls.last.request.headers.get("user-agent")
        assert sent_ua == config.user_agent

    def test_empty_user_agent_rejected(self) -> None:
        with pytest.raises(ValueError, match="user_agent"):
            WaybackConfig(user_agent="")


class TestUsageRequiresContext:
    @pytest.mark.asyncio
    async def test_use_outside_context_raises(self, config: WaybackConfig) -> None:
        client = WaybackClient(config)
        with pytest.raises(RuntimeError):
            await client.query_cdx("https://x.com/a.pdf")
