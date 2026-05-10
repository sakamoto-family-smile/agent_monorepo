"""half_yearly_facility_etl のテスト。

藤沢市の認可・認可外施設一覧 HTML 2 ページを polite fetch → parse → replace_all
する ETL 全体パスを mock で検証する (proposal 0003 §4.5.4)。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx

from fujisawa_platform.crawler import PoliteFetcher, PoliteFetcherConfig
from fujisawa_platform.etl._repos.facilities import FacilityRecord
from fujisawa_platform.etl._runner import EtlRunResult
from fujisawa_platform.etl.half_yearly_facility import (
    FacilityCrawlOutcome,
    crawl_and_replace_facilities,
    run_half_yearly_facility,
)

_AUTHORIZED_URL = "https://www.city.fujisawa.kanagawa.jp/.../ninka.html"
_UNAUTHORIZED_URL = "https://www.city.fujisawa.kanagawa.jp/.../ninkagai.html"


_AUTHORIZED_HTML = """
<html><body>
<h2>公立保育所</h2>
<table>
    <tr><th>施設名</th><th>所在地番</th><th>電話番号</th></tr>
    <tr><td>藤沢保育園</td><td>朝日町 1-1</td><td>0466-12-3456</td></tr>
</table>
<h2>法人等保育所</h2>
<table>
    <tr><th>施設名</th><th>所在地番</th><th>電話番号</th><th>外部リンク</th></tr>
    <tr>
        <td>辻堂保育園</td>
        <td>辻堂 2-2</td>
        <td>0466-22-3456</td>
        <td><a href="https://example.com/tuji">公式 HP</a></td>
    </tr>
</table>
</body></html>
"""

_UNAUTHORIZED_HTML = """
<html><body>
<h2>藤沢駅周辺</h2>
<table>
    <tr><th>施設名(類型)</th><th>所在地</th><th>電話番号</th><th>定員</th></tr>
    <tr>
        <td>A 保育園 (藤沢型 A 型)</td>
        <td>藤沢駅北口徒歩 7 分</td>
        <td>0466-99-0001</td>
        <td>30</td>
    </tr>
</table>
</body></html>
"""


class _RecordingRepo:
    """`FacilitiesRepo` の振る舞い fake。"""

    def __init__(self) -> None:
        self.replaced: list[list[FacilityRecord]] = []

    async def replace_all(self, records: list[FacilityRecord]) -> int:
        self.replaced.append(list(records))
        return len(records)


class _FakeRunsRepo:
    def __init__(self) -> None:
        self.starts: list[dict[str, Any]] = []
        self.finishes: list[dict[str, Any]] = []

    async def start_run(self, **kwargs: Any) -> None:
        self.starts.append(kwargs)

    async def finish_run(self, **kwargs: Any) -> None:
        self.finishes.append(kwargs)

    async def recent_runs(self, job_name: str, *, limit: int = 5) -> list[Any]:
        return []


@pytest.fixture
def fetcher_config() -> PoliteFetcherConfig:
    return PoliteFetcherConfig(
        user_agent="fujisawa-etl-test/0.1 (https://example.com)",
        min_interval_sec=0.001,
        max_retries=1,
        backoff_base_sec=0.001,
    )


# ─────────────────────────────────────────────────────────────────────
# crawl_and_replace_facilities
# ─────────────────────────────────────────────────────────────────────


class TestCrawlAndReplaceFacilities:
    @pytest.mark.asyncio
    @respx.mock
    async def test_replaces_with_combined_records(
        self, fetcher_config: PoliteFetcherConfig
    ) -> None:
        respx.get(_AUTHORIZED_URL).mock(
            return_value=httpx.Response(200, text=_AUTHORIZED_HTML),
        )
        respx.get(_UNAUTHORIZED_URL).mock(
            return_value=httpx.Response(200, text=_UNAUTHORIZED_HTML),
        )
        repo = _RecordingRepo()

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_replace_facilities(
                authorized_url=_AUTHORIZED_URL,
                unauthorized_url=_UNAUTHORIZED_URL,
                fetcher=fetcher,
                repo=repo,  # type: ignore[arg-type]
                now=lambda: datetime(2026, 5, 10, 0, 0, tzinfo=UTC),
            )

        # 認可 2 + 認可外 1 = 3 件
        assert outcome.rows_written == 3
        assert outcome.skipped_empty_rows == 0
        assert len(repo.replaced) == 1
        records = repo.replaced[0]
        assert len(records) == 3

        # 認可テーブル 1 (公立) と認可テーブル 2 (法人等) の facility_type が異なる
        types = {r.facility_type for r in records}
        assert "公立保育所" in types
        assert "法人等保育所" in types
        assert "藤沢型 A 型" in types  # 認可外の括弧内類型

        # source_url が認可・認可外でそれぞれ正しい
        urls_by_type = {r.facility_type: r.source_url for r in records}
        assert urls_by_type["公立保育所"] == _AUTHORIZED_URL
        assert urls_by_type["藤沢型 A 型"] == _UNAUTHORIZED_URL

    @pytest.mark.asyncio
    @respx.mock
    async def test_dry_run_does_not_call_repo(self, fetcher_config: PoliteFetcherConfig) -> None:
        respx.get(_AUTHORIZED_URL).mock(
            return_value=httpx.Response(200, text=_AUTHORIZED_HTML),
        )
        respx.get(_UNAUTHORIZED_URL).mock(
            return_value=httpx.Response(200, text=_UNAUTHORIZED_HTML),
        )
        repo = _RecordingRepo()

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_replace_facilities(
                authorized_url=_AUTHORIZED_URL,
                unauthorized_url=_UNAUTHORIZED_URL,
                fetcher=fetcher,
                repo=repo,  # type: ignore[arg-type]
                dry_run=True,
            )

        assert outcome.rows_written == 3
        assert repo.replaced == []  # DB は叩かない

    @pytest.mark.asyncio
    @respx.mock
    async def test_failure_to_fetch_authorized_propagates(
        self, fetcher_config: PoliteFetcherConfig
    ) -> None:
        """認可 HTML 取得失敗 → 例外を上に伝搬 (run_etl_job ラッパーで failed 化)。"""
        respx.get(_AUTHORIZED_URL).mock(return_value=httpx.Response(500))
        respx.get(_UNAUTHORIZED_URL).mock(
            return_value=httpx.Response(200, text=_UNAUTHORIZED_HTML),
        )
        repo = _RecordingRepo()

        async with PoliteFetcher(fetcher_config) as fetcher:
            with pytest.raises(httpx.HTTPStatusError):
                await crawl_and_replace_facilities(
                    authorized_url=_AUTHORIZED_URL,
                    unauthorized_url=_UNAUTHORIZED_URL,
                    fetcher=fetcher,
                    repo=repo,  # type: ignore[arg-type]
                )

        assert repo.replaced == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_skips_empty_table(self, fetcher_config: PoliteFetcherConfig) -> None:
        """認可外 HTML がテーブルなしでも、認可分は upsert される。"""
        respx.get(_AUTHORIZED_URL).mock(
            return_value=httpx.Response(200, text=_AUTHORIZED_HTML),
        )
        respx.get(_UNAUTHORIZED_URL).mock(
            return_value=httpx.Response(200, text="<html><body></body></html>"),
        )
        repo = _RecordingRepo()

        async with PoliteFetcher(fetcher_config) as fetcher:
            outcome = await crawl_and_replace_facilities(
                authorized_url=_AUTHORIZED_URL,
                unauthorized_url=_UNAUTHORIZED_URL,
                fetcher=fetcher,
                repo=repo,  # type: ignore[arg-type]
            )

        # 認可分 2 件のみ
        assert outcome.rows_written == 2


# ─────────────────────────────────────────────────────────────────────
# run_half_yearly_facility (Cloud Run Job entrypoint)
# ─────────────────────────────────────────────────────────────────────


class TestRunHalfYearlyFacility:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_success_result(self, fetcher_config: PoliteFetcherConfig) -> None:
        respx.get(_AUTHORIZED_URL).mock(
            return_value=httpx.Response(200, text=_AUTHORIZED_HTML),
        )
        respx.get(_UNAUTHORIZED_URL).mock(
            return_value=httpx.Response(200, text=_UNAUTHORIZED_HTML),
        )
        repo = _RecordingRepo()
        runs = _FakeRunsRepo()

        result = await run_half_yearly_facility(
            authorized_url=_AUTHORIZED_URL,
            unauthorized_url=_UNAUTHORIZED_URL,
            fetcher_config=fetcher_config,
            facilities_repo=repo,  # type: ignore[arg-type]
            runs_repo=runs,  # type: ignore[arg-type]
            run_id="half_yearly_facility_etl-20260510-0300",
            now=lambda: datetime(2026, 5, 10, 0, 0, tzinfo=UTC),
        )

        assert isinstance(result, EtlRunResult)
        assert result.status == "success"
        assert result.rows_written == 3
        assert len(runs.finishes) == 1
        assert runs.finishes[0]["status"] == "success"


class TestFacilityCrawlOutcomeModel:
    def test_frozen(self) -> None:
        outcome = FacilityCrawlOutcome(
            rows_written=10,
            skipped_empty_rows=0,
            authorized_hash="a" * 64,
            unauthorized_hash="b" * 64,
        )
        with pytest.raises(Exception):
            outcome.rows_written = 99  # type: ignore[misc]
