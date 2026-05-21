"""ETL Job 共通の実行ラッパー。

各 Job は本体ロジックを `async def` として書き、`run_etl_job` で包んで実行する。
ラッパー側で `etl_runs` テーブルへの記録 / 5 連敗 fail-fast / source_hash skip を一括処理する。

利用例:
    async def my_job():
        return EtlRunResult(rows_written=42, source_hash="<sha256>")

    result = await run_etl_job(
        job_name="weekly_crawl_etl",
        run_id="weekly_crawl_etl-20260510-0300",
        repo=etl_runs_repo,
        fn=my_job,
        probe=lambda: compute_source_hash(...),  # optional
    )
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:  # pragma: no cover
    from fujisawa_platform.etl._repos.etl_runs import EtlRunsRepo


class EtlRunResult(BaseModel):
    """ETL Job 1 回分の結果。

    `fn` が返す場合と、`run_etl_job` ラッパーが組み立てる場合の両方がある。
    `status` の取り得る値は `etl_runs.status` と一致:
        'success' | 'failed' | 'skipped_unchanged'
    """

    model_config = ConfigDict(frozen=True)

    rows_written: int = Field(ge=0, default=0)
    source_hash: str | None = None
    source_url: str | None = None
    status: str = "success"
    error_message: str | None = None


# fail-fast 判定の閾値 (proposal 0003 §4.5.6)。
# 直近 N 件すべて failed なら job 関数を呼ばずに status='failed' を返す。
_FAIL_FAST_THRESHOLD = 5

# orphan `running` レコードの reclassify 閾値。 Cloud Run task timeout の
# 最大値 (24 時間) より十分短く、 通常 Job の実行時間より長い値を選ぶ。
# weekly_crawl は最長 8 時間想定なので 12 時間で十分。
_STALE_RUNNING_HOURS = 12


async def run_etl_job(
    *,
    job_name: str,
    run_id: str,
    repo: EtlRunsRepo,
    fn: Callable[[], Awaitable[EtlRunResult]],
    probe: Callable[[], Awaitable[str | None]] | None = None,
    now: Callable[[], datetime] | None = None,
) -> EtlRunResult:
    """ETL Job を実行し、`etl_runs` への記録 / fail-fast / skip を行う。

    Args:
        job_name: ETL Job 識別子 (`etl_runs.job_name` カラムに対応)。
        run_id: 実行回識別子 (例: `weekly_crawl_etl-20260510-0300`)。
        repo: `EtlRunsRepo` (DI 可能)。
        fn: 実 Job ロジック。`EtlRunResult` を返す async 関数。
        probe: 任意。事前に source_hash を計算して返す async 関数。
            前回 success の source_hash と一致したら fn を呼ばず skip。
        now: 任意。datetime.now の差し替え (テスト用)。
    """
    _now = now or _utcnow
    started_at = _now()

    # orphan な `running` レコードを `aborted` に書き換える (Cloud Run task
    # timeout で強制終了されて finish_run が呼ばれなかったケースの後始末)。
    # 後続の recent_runs / fail-fast 判定が正確な状態を見られるよう、 最初に行う。
    try:
        await repo.abort_stale_running(
            job_name=job_name, now=started_at, stale_after_hours=_STALE_RUNNING_HOURS
        )
    except AttributeError:  # pragma: no cover — 旧 repo (テストの簡易 mock) との互換性
        pass

    # fail-fast 判定 (直近 N 件すべて failed なら fn を呼ばずに失敗扱い)
    recent = await repo.recent_runs(job_name, limit=_FAIL_FAST_THRESHOLD)
    if _should_fail_fast(recent):
        await repo.start_run(
            job_name=job_name, run_id=run_id, started_at=started_at, source_url=None
        )
        message = (
            f"fail-fast: 直近 {_FAIL_FAST_THRESHOLD} 件すべて failed のため、"
            "Job 関数を実行せず手動再開を待ちます (proposal 0003 §4.5.6)"
        )
        finished_at = _now()
        await repo.finish_run(
            job_name=job_name,
            run_id=run_id,
            finished_at=finished_at,
            status="failed",
            error_message=message,
        )
        return EtlRunResult(status="failed", error_message=message)

    # source_hash skip 判定 (前回 success と一致するならスキップ)
    if probe is not None:
        candidate_hash = await probe()
        last_success_hash = _last_success_hash(recent)
        if candidate_hash is not None and candidate_hash == last_success_hash:
            await repo.start_run(
                job_name=job_name,
                run_id=run_id,
                started_at=started_at,
                source_url=None,
            )
            finished_at = _now()
            await repo.finish_run(
                job_name=job_name,
                run_id=run_id,
                finished_at=finished_at,
                status="skipped_unchanged",
                source_hash=candidate_hash,
            )
            return EtlRunResult(status="skipped_unchanged", source_hash=candidate_hash)

    # 通常実行
    await repo.start_run(job_name=job_name, run_id=run_id, started_at=started_at, source_url=None)
    try:
        result = await fn()
    except Exception as exc:  # noqa: BLE001 — Job 内例外を fail として記録するため広く捕捉
        finished_at = _now()
        message = f"{type(exc).__name__}: {exc}"
        await repo.finish_run(
            job_name=job_name,
            run_id=run_id,
            finished_at=finished_at,
            status="failed",
            error_message=message,
        )
        return EtlRunResult(status="failed", error_message=message)

    finished_at = _now()
    await repo.finish_run(
        job_name=job_name,
        run_id=run_id,
        finished_at=finished_at,
        status=result.status or "success",
        source_hash=result.source_hash,
        rows_written=result.rows_written,
    )
    return result.model_copy(update={"status": result.status or "success"})


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _should_fail_fast(recent: list) -> bool:  # type: ignore[type-arg]
    if len(recent) < _FAIL_FAST_THRESHOLD:
        return False
    return all(r.status == "failed" for r in recent[:_FAIL_FAST_THRESHOLD])


def _last_success_hash(recent: list) -> str | None:  # type: ignore[type-arg]
    for record in recent:
        if record.status == "success" and record.source_hash:
            return record.source_hash
    return None


__all__ = ["EtlRunResult", "run_etl_job"]
