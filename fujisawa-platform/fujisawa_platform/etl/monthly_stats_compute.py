"""monthly_stats_compute: admission_results 集計 → competition_stats 更新 (DB 内のみ)。

実行頻度 (proposal 0003 §4.5.4): 毎月 23 日 03:00 JST、Cloud Run Job として配備。
**外部 fetch なし** の Job (proposal 表の括弧書きで明示)。

処理フロー:
  [1] admission_results を直近 3 年分読み出す (1 次のみ集計対象)
  [2] (facility_id, age_class) でグループ化
  [3] 各グループに対して `stats_compute.compute_competition_stats` を呼ぶ
  [4] CompetitionStatsRepo.upsert_many で competition_stats を更新

書き込み先テーブル: `competition_stats` (PK: facility_id × age_class)
利用先: 保活 StrategyAgent (proposal 0005)。

archive / fetcher は不要 (外部リソースを叩かないため、PdfArchive DI も省略)。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict

from fujisawa_platform.etl._repos.admission import AdmissionResultRecord
from fujisawa_platform.etl._repos.competition_stats import CompetitionStatsRecord
from fujisawa_platform.etl._runner import EtlRunResult, run_etl_job
from fujisawa_platform.etl.stats_compute import compute_competition_stats

if TYPE_CHECKING:  # pragma: no cover
    from fujisawa_platform.etl._repos.etl_runs import EtlRunsRepo


class _AdmissionRepoLike(Protocol):
    async def list_recent_years(
        self, *, min_year: int, max_year: int
    ) -> list[AdmissionResultRecord]: ...


class _StatsRepoLike(Protocol):
    async def upsert_many(self, records: list[CompetitionStatsRecord]) -> int: ...


_LOOKBACK_YEARS = 3


class StatsComputeOutcome(BaseModel):
    """`compute_stats` の戻り値。"""

    model_config = ConfigDict(frozen=True)

    rows_written: int = 0
    facilities_processed: int = 0


async def compute_stats(
    *,
    admission_repo: _AdmissionRepoLike,
    stats_repo: _StatsRepoLike,
    current_year: int,
    now: Callable[[], datetime] | None = None,
    dry_run: bool = False,
) -> StatsComputeOutcome:
    """admission_results を集計 → competition_stats を upsert。

    Args:
        admission_repo: `list_recent_years(min_year, max_year)` を持つ Repository。
        stats_repo: `upsert_many` を持つ Repository。
        current_year: 集計起点 (本年)。 直近 3 年 (current_year - 2 .. current_year) を読む。
        now: last_updated 用 (テスト差し替え可能)。
        dry_run: True なら集計は行うが `stats_repo.upsert_many` を呼ばない。
    """
    _now = now or _utcnow
    min_year = current_year - (_LOOKBACK_YEARS - 1)
    admissions = await admission_repo.list_recent_years(min_year=min_year, max_year=current_year)

    # (facility_id, age_class) ごとにグループ化
    groups: dict[tuple[str, int], list[AdmissionResultRecord]] = defaultdict(list)
    for rec in admissions:
        groups[(rec.facility_id, rec.age_class)].append(rec)

    stats_records: list[CompetitionStatsRecord] = []
    for (facility_id, age_class), recs in groups.items():
        stats_records.append(
            compute_competition_stats(
                facility_id=facility_id,
                age_class=age_class,
                admissions=recs,
                now=_now,
            )
        )

    if not dry_run and stats_records:
        await stats_repo.upsert_many(stats_records)

    facilities = {fac_id for (fac_id, _) in groups.keys()}
    return StatsComputeOutcome(
        rows_written=len(stats_records),
        facilities_processed=len(facilities),
    )


async def run_monthly_stats_compute(
    *,
    admission_repo: _AdmissionRepoLike,
    stats_repo: _StatsRepoLike,
    runs_repo: EtlRunsRepo,
    run_id: str,
    current_year: int,
    now: Callable[[], datetime] | None = None,
    dry_run: bool = False,
) -> EtlRunResult:
    """Cloud Run Job のエントリポイント (run_etl_job ラップ)。外部 fetch なし。"""

    async def _job() -> EtlRunResult:
        outcome = await compute_stats(
            admission_repo=admission_repo,
            stats_repo=stats_repo,
            current_year=current_year,
            now=now,
            dry_run=dry_run,
        )
        return EtlRunResult(
            rows_written=outcome.rows_written,
            source_url=None,
            source_hash=None,
            status="success",
        )

    return await run_etl_job(
        job_name="monthly_stats_compute",
        run_id=run_id,
        repo=runs_repo,
        fn=_job,
        now=now,
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = ["StatsComputeOutcome", "compute_stats", "run_monthly_stats_compute"]
