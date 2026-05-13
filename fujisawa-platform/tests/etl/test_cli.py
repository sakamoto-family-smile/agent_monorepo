"""etl.cli (Cloud Run Job 用 entrypoint) のテスト。

CLI 起動から各 Job への dispatch を、heavy dependency (asyncpg pool / Vertex / Docling) を
mock で差し替えた状態で検証する。実 DB / 実 HTTP は呼ばない。
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

from fujisawa_platform.etl import cli


class _RecordedCall:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] | None = None
        self.call_count = 0

    def __call__(self, **kwargs: Any) -> _Awaitable:
        self.kwargs = kwargs
        self.call_count += 1
        return _Awaitable(self.kwargs)


class _Awaitable:
    """単純な awaitable: await したら EtlRunResult-like object を返す。"""

    def __init__(self, kwargs: dict[str, Any] | None) -> None:
        self._kwargs = kwargs

    def __await__(self):  # type: ignore[no-untyped-def]
        return iter([])


@pytest.fixture
def stub_resources(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """重い依存を全て fake に差し替えるフィクスチャ。"""
    captured: dict[str, Any] = {}

    # 1) build_pgvector_pool → fake pool
    async def fake_build_pool(**kwargs: Any) -> object:
        captured["build_pool_kwargs"] = kwargs
        return object()

    monkeypatch.setattr(cli, "build_pgvector_pool", fake_build_pool)

    # 2) pool.close() → no-op
    async def fake_close() -> None:
        captured["pool_closed"] = True

    # 3) 各 run_<job_name> を fake に差し替え
    run_calls: dict[str, _RecordedCall] = {}
    for name in (
        "run_weekly_crawl",
        "run_half_yearly_facility",
        "run_biyearly_admission",
        "run_monthly_vacancy",
        "run_yearly_navi",
        "run_monthly_stats_compute",
        "run_wayback_backfill",
    ):
        recorded = _RecordedCall()
        run_calls[name] = recorded
        monkeypatch.setattr(cli, name, recorded)

    # 4) EmbeddingClient / Resolver / Archive をシンプルに置き換え
    monkeypatch.setattr(cli, "_make_embedder", lambda config: object())
    monkeypatch.setattr(cli, "_make_archive", lambda config: object())

    async def fake_build_resolver(repo: Any, **_kwargs: Any) -> object:
        captured["resolver_built"] = True
        return object()

    monkeypatch.setattr(cli, "build_facility_resolver", fake_build_resolver)

    # 5) `pool.close` を simulate
    class _FakePool:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    fake_pool = _FakePool()

    async def fake_build_pool_v2(**kwargs: Any) -> _FakePool:
        captured["build_pool_kwargs"] = kwargs
        captured["pool"] = fake_pool
        return fake_pool

    monkeypatch.setattr(cli, "build_pgvector_pool", fake_build_pool_v2)

    captured["run_calls"] = run_calls
    return captured


@pytest.fixture
def base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """EtlConfig 必須項目を環境変数で設定。"""
    monkeypatch.setenv("FUJISAWA_ETL_DB_HOST", "127.0.0.1")
    monkeypatch.setenv("FUJISAWA_ETL_DB_USER", "etl_user")
    monkeypatch.setenv("FUJISAWA_ETL_DB_PASSWORD", "test-secret")
    monkeypatch.setenv("FUJISAWA_ETL_USER_AGENT", "fujisawa-etl-test/0.1 (https://example.com)")
    monkeypatch.setenv(
        "FUJISAWA_ETL_SITEMAP_URL",
        "https://www.city.fujisawa.kanagawa.jp/sitemap.xml",
    )


# ─────────────────────────────────────────────────────────────────────
# Dispatch tests
# ─────────────────────────────────────────────────────────────────────


class TestDispatch:
    @pytest.mark.asyncio
    async def test_weekly_crawl_routes_to_run_weekly_crawl(
        self, base_env: None, stub_resources: dict[str, Any]
    ) -> None:
        await cli.main_async(["weekly_crawl"])
        assert stub_resources["run_calls"]["run_weekly_crawl"].call_count == 1
        # 他の Job は呼ばれない
        for name, recorded in stub_resources["run_calls"].items():
            if name != "run_weekly_crawl":
                assert recorded.call_count == 0, f"{name} should not be called"

    @pytest.mark.asyncio
    async def test_half_yearly_facility_routes_correctly(
        self, base_env: None, stub_resources: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "FUJISAWA_ETL_AUTHORIZED_FACILITIES_URL", "https://example.com/auth.html"
        )
        monkeypatch.setenv(
            "FUJISAWA_ETL_UNAUTHORIZED_FACILITIES_URL", "https://example.com/unauth.html"
        )
        await cli.main_async(["half_yearly_facility"])
        assert stub_resources["run_calls"]["run_half_yearly_facility"].call_count == 1

    @pytest.mark.asyncio
    async def test_biyearly_admission_routes_correctly(
        self, base_env: None, stub_resources: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FUJISAWA_ETL_ADMISSION_PDF_URL_1ST", "https://example.com/r8-1st.pdf")
        monkeypatch.setenv("FUJISAWA_ETL_ADMISSION_YEAR", "2026")
        await cli.main_async(["biyearly_admission", "--round", "1st"])
        assert stub_resources["run_calls"]["run_biyearly_admission"].call_count == 1
        assert stub_resources["resolver_built"] is True

    @pytest.mark.asyncio
    async def test_monthly_vacancy_routes_correctly(
        self, base_env: None, stub_resources: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FUJISAWA_ETL_VACANCY_PDF_URL", "https://example.com/v.pdf")
        monkeypatch.setenv("FUJISAWA_ETL_APPLICATION_PDF_URL", "https://example.com/a.pdf")
        monkeypatch.setenv("FUJISAWA_ETL_VACANCY_YEAR_MONTH", "2026-04")
        await cli.main_async(["monthly_vacancy"])
        assert stub_resources["run_calls"]["run_monthly_vacancy"].call_count == 1

    @pytest.mark.asyncio
    async def test_yearly_navi_routes_correctly(
        self, base_env: None, stub_resources: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FUJISAWA_ETL_NAVI_PDF_URL", "https://example.com/navi.pdf")
        monkeypatch.setenv("FUJISAWA_ETL_NAVI_YEAR", "2026")
        await cli.main_async(["yearly_navi"])
        assert stub_resources["run_calls"]["run_yearly_navi"].call_count == 1

    @pytest.mark.asyncio
    async def test_monthly_stats_compute_routes_correctly(
        self, base_env: None, stub_resources: dict[str, Any]
    ) -> None:
        await cli.main_async(["monthly_stats_compute", "--current-year", "2026"])
        assert stub_resources["run_calls"]["run_monthly_stats_compute"].call_count == 1

    @pytest.mark.asyncio
    async def test_wayback_backfill_routes_correctly(
        self, base_env: None, stub_resources: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # wayback_backfill_enabled=true を明示
        monkeypatch.setenv("FUJISAWA_ETL_WAYBACK_BACKFILL_ENABLED", "true")
        await cli.main_async(["wayback_backfill"])
        recorded = stub_resources["run_calls"]["run_wayback_backfill"]
        assert recorded.call_count == 1
        # items は wayback_items.RUNTIME_ITEMS から list 化されて渡る (Phase 4-2h step 3-2)
        from fujisawa_platform.etl.wayback_items import RUNTIME_ITEMS

        assert recorded.kwargs is not None
        assert recorded.kwargs["items"] == list(RUNTIME_ITEMS)

    @pytest.mark.asyncio
    async def test_unknown_job_raises(self, base_env: None, stub_resources: dict[str, Any]) -> None:
        with pytest.raises(SystemExit):
            await cli.main_async(["bogus_job"])


# ─────────────────────────────────────────────────────────────────────
# Enabled / disabled (Phase 0 段階導入)
# ─────────────────────────────────────────────────────────────────────


class TestEnabledFlag:
    @pytest.mark.asyncio
    async def test_disabled_job_skips_without_running(
        self, base_env: None, stub_resources: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`FUJISAWA_ETL_WEEKLY_CRAWL_ENABLED=false` で skip。"""
        monkeypatch.setenv("FUJISAWA_ETL_WEEKLY_CRAWL_ENABLED", "false")
        exit_code = await cli.main_async(["weekly_crawl"])
        assert exit_code == 0
        # run_weekly_crawl は呼ばれない (skip)
        assert stub_resources["run_calls"]["run_weekly_crawl"].call_count == 0

    @pytest.mark.asyncio
    async def test_wayback_backfill_disabled_by_default(
        self, base_env: None, stub_resources: dict[str, Any]
    ) -> None:
        """wayback_backfill_enabled は default false。"""
        exit_code = await cli.main_async(["wayback_backfill"])
        assert exit_code == 0
        assert stub_resources["run_calls"]["run_wayback_backfill"].call_count == 0


# ─────────────────────────────────────────────────────────────────────
# Lifecycle: pool は必ず close される
# ─────────────────────────────────────────────────────────────────────


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_pool_closed_after_success(
        self, base_env: None, stub_resources: dict[str, Any]
    ) -> None:
        await cli.main_async(["monthly_stats_compute", "--current-year", "2026"])
        assert stub_resources["pool"].closed is True

    @pytest.mark.asyncio
    async def test_pool_closed_after_failure(
        self, base_env: None, stub_resources: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Job が例外を投げても pool.close() は呼ばれる。"""

        async def failing_run(**_kwargs: Any) -> Any:
            raise RuntimeError("simulated DB failure")

        monkeypatch.setattr(cli, "run_monthly_stats_compute", failing_run)

        with pytest.raises(RuntimeError, match="simulated DB failure"):
            await cli.main_async(["monthly_stats_compute", "--current-year", "2026"])
        assert stub_resources["pool"].closed is True


# ─────────────────────────────────────────────────────────────────────
# Sync entry point (main)
# ─────────────────────────────────────────────────────────────────────


class TestSyncMain:
    def test_main_calls_asyncio_run(
        self, base_env: None, stub_resources: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`cli.main()` が `asyncio.run` で `main_async` を呼ぶ。"""
        monkeypatch.setattr(sys, "argv", ["fujisawa-etl", "monthly_stats_compute"])
        exit_code = cli.main()
        assert exit_code == 0
        assert stub_resources["run_calls"]["run_monthly_stats_compute"].call_count == 1
