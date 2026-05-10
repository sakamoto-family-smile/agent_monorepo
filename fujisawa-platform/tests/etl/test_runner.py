"""run_etl_job の振る舞いテスト。

- started_at で start_run、終了時に finish_run を呼ぶ
- 例外時は status='failed' + error_message
- source_hash が前回の `success` と一致するなら status='skipped_unchanged'
- 過去 5 件すべて failed なら fail-fast (job 関数を呼ばずに status='failed')
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from fujisawa_platform.etl._repos.etl_runs import EtlRunRecord
from fujisawa_platform.etl._runner import EtlRunResult, run_etl_job


class _FakeRepo:
    """EtlRunsRepo の振る舞い fake (実 SQL は叩かず内部 list で記録)。"""

    def __init__(self, *, recent: list[EtlRunRecord] | None = None) -> None:
        self.starts: list[dict[str, Any]] = []
        self.finishes: list[dict[str, Any]] = []
        self._recent = recent or []

    async def start_run(self, **kwargs: Any) -> None:
        self.starts.append(kwargs)

    async def finish_run(self, **kwargs: Any) -> None:
        self.finishes.append(kwargs)

    async def recent_runs(self, job_name: str, *, limit: int = 5) -> list[EtlRunRecord]:
        return self._recent[:limit]


def _record(*, run_id: str, status: str, source_hash: str | None = None) -> EtlRunRecord:
    return EtlRunRecord(
        job_name="weekly_crawl_etl",
        run_id=run_id,
        started_at=datetime(2026, 5, 1, 3, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 1, 4, 0, tzinfo=UTC),
        status=status,
        source_url=None,
        source_hash=source_hash,
        rows_written=0,
        error_message=None,
    )


@pytest.fixture
def repo() -> _FakeRepo:
    return _FakeRepo()


class TestSuccessPath:
    @pytest.mark.asyncio
    async def test_records_start_and_finish(self, repo: _FakeRepo) -> None:
        async def job_fn() -> EtlRunResult:
            return EtlRunResult(
                rows_written=42,
                source_hash="a" * 64,
                source_url="https://example.com/x",
            )

        result = await run_etl_job(
            job_name="weekly_crawl_etl",
            run_id="run-1",
            repo=repo,  # type: ignore[arg-type]
            fn=job_fn,
        )

        assert result.status == "success"
        assert result.rows_written == 42
        assert len(repo.starts) == 1
        assert len(repo.finishes) == 1
        assert repo.finishes[0]["status"] == "success"
        assert repo.finishes[0]["rows_written"] == 42
        assert repo.finishes[0]["source_hash"] == "a" * 64

    @pytest.mark.asyncio
    async def test_passes_started_at_to_repo(self, repo: _FakeRepo) -> None:
        called_at = datetime(2026, 5, 10, 3, 0, tzinfo=UTC)

        async def job_fn() -> EtlRunResult:
            return EtlRunResult(rows_written=0, source_hash=None)

        await run_etl_job(
            job_name="weekly_crawl_etl",
            run_id="run-1",
            repo=repo,  # type: ignore[arg-type]
            fn=job_fn,
            now=lambda: called_at,
        )

        assert repo.starts[0]["started_at"] == called_at


class TestFailurePath:
    @pytest.mark.asyncio
    async def test_records_failed_status_with_error_message(self, repo: _FakeRepo) -> None:
        async def job_fn() -> EtlRunResult:
            raise RuntimeError("Cloud SQL connection lost")

        result = await run_etl_job(
            job_name="weekly_crawl_etl",
            run_id="run-1",
            repo=repo,  # type: ignore[arg-type]
            fn=job_fn,
        )

        assert result.status == "failed"
        assert result.error_message is not None
        assert "Cloud SQL" in result.error_message
        assert repo.finishes[0]["status"] == "failed"
        assert "Cloud SQL" in repo.finishes[0]["error_message"]


class TestSkipUnchanged:
    @pytest.mark.asyncio
    async def test_skips_when_source_hash_matches_last_success(self) -> None:
        last_hash = "b" * 64
        repo = _FakeRepo(recent=[_record(run_id="prev", status="success", source_hash=last_hash)])

        # job_fn は __probe__ モードで source_hash を計算する想定 (今回は固定値を返す stub)
        called = False

        async def probe_fn() -> str | None:
            return last_hash

        async def job_fn() -> EtlRunResult:
            nonlocal called
            called = True
            return EtlRunResult(rows_written=0, source_hash=None)

        result = await run_etl_job(
            job_name="weekly_crawl_etl",
            run_id="run-1",
            repo=repo,  # type: ignore[arg-type]
            fn=job_fn,
            probe=probe_fn,
        )

        assert result.status == "skipped_unchanged"
        assert called is False  # job_fn は実行されない
        assert repo.finishes[0]["status"] == "skipped_unchanged"
        assert repo.finishes[0]["source_hash"] == last_hash

    @pytest.mark.asyncio
    async def test_runs_when_source_hash_differs(self) -> None:
        repo = _FakeRepo(recent=[_record(run_id="prev", status="success", source_hash="OLD")])

        async def probe_fn() -> str | None:
            return "NEW"

        async def job_fn() -> EtlRunResult:
            return EtlRunResult(rows_written=10, source_hash="NEW")

        result = await run_etl_job(
            job_name="weekly_crawl_etl",
            run_id="run-1",
            repo=repo,  # type: ignore[arg-type]
            fn=job_fn,
            probe=probe_fn,
        )
        assert result.status == "success"
        assert result.rows_written == 10


class TestFailFast:
    @pytest.mark.asyncio
    async def test_skips_when_recent_5_all_failed(self) -> None:
        repo = _FakeRepo(
            recent=[_record(run_id=f"prev-{i}", status="failed") for i in range(5)],
        )
        called = False

        async def job_fn() -> EtlRunResult:
            nonlocal called
            called = True
            return EtlRunResult(rows_written=0, source_hash=None)

        result = await run_etl_job(
            job_name="weekly_crawl_etl",
            run_id="run-1",
            repo=repo,  # type: ignore[arg-type]
            fn=job_fn,
        )

        assert result.status == "failed"
        assert called is False
        assert "fail-fast" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_does_not_fail_fast_when_recent_includes_success(
        self,
    ) -> None:
        recent = [
            _record(run_id=f"prev-{i}", status="failed" if i != 2 else "success") for i in range(5)
        ]
        repo = _FakeRepo(recent=recent)
        called = False

        async def job_fn() -> EtlRunResult:
            nonlocal called
            called = True
            return EtlRunResult(rows_written=1, source_hash=None)

        result = await run_etl_job(
            job_name="weekly_crawl_etl",
            run_id="run-1",
            repo=repo,  # type: ignore[arg-type]
            fn=job_fn,
        )
        assert called is True
        assert result.status == "success"


class TestEtlRunResultModel:
    def test_frozen(self) -> None:
        result = EtlRunResult(
            rows_written=10,
            source_hash="a" * 64,
            source_url=None,
            status="success",
            error_message=None,
        )
        with pytest.raises(Exception):
            result.rows_written = 20  # type: ignore[misc]
