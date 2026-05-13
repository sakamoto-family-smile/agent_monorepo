"""ETL Job の Cloud Run Job entrypoint (CLI dispatcher)。

実行例:
    python -m fujisawa_platform.etl.cli weekly_crawl
    python -m fujisawa_platform.etl.cli biyearly_admission --round 1st
    python -m fujisawa_platform.etl.cli monthly_stats_compute --current-year 2026

Cloud Run Job の CMD は `["python", "-m", "fujisawa_platform.etl.cli", "<job_name>"]`。
追加の引数 (round / current_year 等) は引数として渡す、ファイル単位の URL は env。

共通の前処理:
- `EtlConfig` を env から読み込み
- `asyncpg.Pool` を構築 (pgvector extra)
- `PdfArchive` を `pdf_archive_backend` env から組み立て
- 各 Job 専用の Repo / Embedding / Resolver を必要時に組み立て

Job ごとの個別ロジック:
- args / env / config を見て対応する `run_<job_name>(...)` を呼ぶ

各 Job の `enabled` フラグ (`FUJISAWA_ETL_<JOB>_ENABLED=false`) が false なら、
fn を呼ばずに skip (Phase 0 で段階導入するため、proposal 0003 §4.8)。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from fujisawa_platform.etl._repos.admission import AdmissionRepo
from fujisawa_platform.etl._repos.competition_stats import CompetitionStatsRepo
from fujisawa_platform.etl._repos.etl_runs import EtlRunsRepo
from fujisawa_platform.etl._repos.facilities import FacilitiesRepo
from fujisawa_platform.etl._repos.pdf_documents import PdfDocumentsRepo
from fujisawa_platform.etl._repos.vacancy import ApplicationRepo, VacancyRepo
from fujisawa_platform.etl.biyearly_admission import run_biyearly_admission
from fujisawa_platform.etl.config import EtlConfig
from fujisawa_platform.etl.facility_resolver_builder import build_facility_resolver
from fujisawa_platform.etl.half_yearly_facility import run_half_yearly_facility
from fujisawa_platform.etl.monthly_stats_compute import run_monthly_stats_compute
from fujisawa_platform.etl.monthly_vacancy import run_monthly_vacancy
from fujisawa_platform.etl.pdf_archive import build_archive_from_config
from fujisawa_platform.etl.wayback_backfill import run_wayback_backfill
from fujisawa_platform.etl.wayback_items import RUNTIME_ITEMS as _WAYBACK_ITEMS
from fujisawa_platform.etl.weekly_crawl import run_weekly_crawl
from fujisawa_platform.etl.yearly_navi import run_yearly_navi
from fujisawa_platform.knowledge_base import (
    EmbeddingClient,
    MockEmbeddingClient,
    PgvectorStore,
    build_pgvector_pool,
)

if TYPE_CHECKING:  # pragma: no cover
    from fujisawa_platform.etl.pdf_archive import PdfArchive

logger = logging.getLogger(__name__)


# Job 名 → enabled フラグ属性名のマッピング
_ENABLED_FLAG: dict[str, str] = {
    "weekly_crawl": "weekly_crawl_enabled",
    "half_yearly_facility": "half_yearly_facility_enabled",
    "biyearly_admission": "biyearly_admission_enabled",
    "monthly_vacancy": "monthly_vacancy_enabled",
    "yearly_navi": "yearly_navi_enabled",
    "monthly_stats_compute": "monthly_stats_compute_enabled",
    "wayback_backfill": "wayback_backfill_enabled",
}


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fujisawa-etl",
        description="fujisawa-platform ETL Job dispatcher",
    )
    parser.add_argument(
        "job",
        choices=sorted(_ENABLED_FLAG.keys()),
        help="実行する ETL Job 名",
    )
    parser.add_argument(
        "--round",
        choices=["1st", "2nd"],
        help="biyearly_admission の round 指定 ('1st' or '2nd')",
    )
    parser.add_argument(
        "--current-year",
        type=int,
        help="monthly_stats_compute の集計起点年度",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse / archive は実行するが DB upsert はしない",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="etl_runs.run_id を上書き (default は自動生成)",
    )
    return parser.parse_args(argv)


async def main_async(argv: list[str]) -> int:
    """非同期エントリポイント。テストはこれを直接呼ぶ。"""
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    config = EtlConfig()  # type: ignore[call-arg]  # env から自動ロード
    if not _is_enabled(config, args.job):
        logger.info("job %s is disabled, skipping", args.job)
        return 0

    pool = await build_pgvector_pool(
        host=config.db_host,
        port=config.db_port,
        user=config.db_user,
        password=config.db_password,
        database=config.db_name,
        min_size=config.db_pool_min,
        max_size=config.db_pool_max,
    )
    try:
        run_id = args.run_id or _generate_run_id(args.job)
        result = await _dispatch(
            job=args.job,
            pool=pool,
            config=config,
            run_id=run_id,
            args=args,
        )
        logger.info(
            "job %s finished: %s",
            args.job,
            json.dumps(result, ensure_ascii=False, default=str) if result else "(no result)",
        )
        return 0
    finally:
        await pool.close()


async def _dispatch(
    *,
    job: str,
    pool: Any,
    config: EtlConfig,
    run_id: str,
    args: argparse.Namespace,
) -> Any:
    """Job 名 → run_<job_name> へ振り分け。"""
    runs_repo = EtlRunsRepo(pool=pool)
    archive = _make_archive(config)
    embedder = _make_embedder(config)

    if job == "weekly_crawl":
        store = PgvectorStore(pool=pool, embedding_dim=config.embedding_dim)
        return await run_weekly_crawl(
            sitemap_url=config.sitemap_url,
            fetcher_config=_fetcher_config(config),
            embedder=embedder,
            store=store,
            runs_repo=runs_repo,
            run_id=run_id,
            dry_run=args.dry_run,
        )

    if job == "half_yearly_facility":
        return await run_half_yearly_facility(
            authorized_url=config.authorized_facilities_url,
            unauthorized_url=config.unauthorized_facilities_url,
            fetcher_config=_fetcher_config(config),
            facilities_repo=FacilitiesRepo(pool=pool),
            runs_repo=runs_repo,
            run_id=run_id,
            dry_run=args.dry_run,
        )

    if job == "biyearly_admission":
        round_value = args.round
        if not round_value:
            raise SystemExit("biyearly_admission requires --round 1st|2nd")
        pdf_url = (
            config.admission_pdf_url_1st if round_value == "1st" else config.admission_pdf_url_2nd
        )
        resolver = await build_facility_resolver(FacilitiesRepo(pool=pool))
        return await run_biyearly_admission(
            pdf_url=pdf_url,
            year=config.admission_year,
            round=round_value,
            fetcher_config=_fetcher_config(config),
            admission_repo=AdmissionRepo(pool=pool),
            runs_repo=runs_repo,
            resolver=resolver,
            run_id=run_id,
            archive=archive,
            dry_run=args.dry_run,
        )

    if job == "monthly_vacancy":
        snapshot_date = _parse_snapshot_date(config.vacancy_year_month)
        resolver = await build_facility_resolver(FacilitiesRepo(pool=pool))
        return await run_monthly_vacancy(
            vacancy_pdf_url=config.vacancy_pdf_url,
            application_pdf_url=config.application_pdf_url,
            year_month=config.vacancy_year_month,
            snapshot_date=snapshot_date,
            fetcher_config=_fetcher_config(config),
            vacancy_repo=VacancyRepo(pool=pool),
            application_repo=ApplicationRepo(pool=pool),
            runs_repo=runs_repo,
            resolver=resolver,
            run_id=run_id,
            archive=archive,
            dry_run=args.dry_run,
        )

    if job == "yearly_navi":
        return await run_yearly_navi(
            pdf_url=config.navi_pdf_url,
            year=config.navi_year,
            fetcher_config=_fetcher_config(config),
            docs_repo=PdfDocumentsRepo(pool=pool),
            runs_repo=runs_repo,
            embedder=embedder,
            run_id=run_id,
            archive=archive,
            dry_run=args.dry_run,
        )

    if job == "monthly_stats_compute":
        current_year = args.current_year or datetime.now(UTC).year
        return await run_monthly_stats_compute(
            admission_repo=AdmissionRepo(pool=pool),
            stats_repo=CompetitionStatsRepo(pool=pool),
            runs_repo=runs_repo,
            run_id=run_id,
            current_year=current_year,
            dry_run=args.dry_run,
        )

    if job == "wayback_backfill":
        # 実 BackfillItem リストは `wayback_items.RUNTIME_ITEMS` に固定で持つ
        # (Phase 4-2h step 3-2、investigation note §A2-1 由来)。
        from fujisawa_platform.crawler import WaybackConfig

        resolver = await build_facility_resolver(FacilitiesRepo(pool=pool))
        return await run_wayback_backfill(
            items=list(_WAYBACK_ITEMS),
            wayback_config=WaybackConfig(user_agent=config.user_agent),
            admission_repo=AdmissionRepo(pool=pool),
            runs_repo=runs_repo,
            resolver=resolver,
            run_id=run_id,
            archive=archive,
            dry_run=args.dry_run,
        )

    raise SystemExit(f"unknown job: {job}")


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _is_enabled(config: EtlConfig, job: str) -> bool:
    flag = _ENABLED_FLAG.get(job)
    if flag is None:
        return False
    return bool(getattr(config, flag))


def _fetcher_config(config: EtlConfig) -> Any:
    """`PoliteFetcherConfig` を構築。crawler の lazy import を避けるためここで遅延 import。"""
    from fujisawa_platform.crawler import PoliteFetcherConfig

    return PoliteFetcherConfig(
        user_agent=config.user_agent,
        min_interval_sec=config.min_interval_sec,
    )


def _make_archive(config: EtlConfig) -> PdfArchive:
    from pathlib import Path

    return build_archive_from_config(
        backend=config.pdf_archive_backend,
        bucket=config.pdf_archive_bucket,
        local_root=Path(config.pdf_archive_local_root),
    )


def _make_embedder(config: EtlConfig) -> EmbeddingClient:
    """Vertex AI を有効化する条件で切り替え (Phase 4-2h step 2 で本番化)。"""
    if not config.vertex_project_id:
        logger.warning("vertex_project_id not set; using MockEmbeddingClient")
        return MockEmbeddingClient(dimension=config.embedding_dim)
    # Phase 4-2h step 2 で VertexEmbeddingClient に差し替え予定
    return MockEmbeddingClient(dimension=config.embedding_dim)


def _generate_run_id(job: str) -> str:
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    suffix = uuid.uuid4().hex[:6]
    return f"{job}-{ts}-{suffix}"


def _parse_snapshot_date(year_month: str) -> date:
    """`'2026-04'` → `date(2026, 4, 1)` (月初を snapshot_date として使う)。"""
    if not year_month:
        raise SystemExit("monthly_vacancy requires FUJISAWA_ETL_VACANCY_YEAR_MONTH")
    year, month = year_month.split("-", 1)
    return date(int(year), int(month), 1)


def main() -> int:
    """sync entrypoint (Cloud Run Job の CMD で呼ばれる)。"""
    return asyncio.run(main_async(sys.argv[1:]))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
