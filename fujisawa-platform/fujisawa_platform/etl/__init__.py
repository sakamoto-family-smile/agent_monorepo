"""etl module: ETL Cloud Run Jobs の entrypoint と共通基盤。

各 Job は `run_<job_name>(*, pool, ...)` という async 関数として実装し、
Cloud Run Job のエントリポイントから呼ばれる (Phase 4-2h で terraform 配備)。

Phase 4-2 の進行状況:
- 4-2a: 共通フレーム (`_runner` / `EtlRunsRepo` / `_html`) + `weekly_crawl_etl`
- 4-2b: `half_yearly_facility_etl`
- 4-2c: `biyearly_admission_etl`
- 4-2c-2: `PdfArchive` (GcsArchive / LocalArchive / NullArchive)
- 4-2d: `monthly_vacancy_etl`
- 4-2e: `yearly_navi_etl`
- 4-2f: `monthly_stats_compute` (TBD)
- 4-2g: `wayback_backfill` (TBD, 一度きり)
"""

from fujisawa_platform.etl._runner import EtlRunResult, run_etl_job
from fujisawa_platform.etl.biyearly_admission import (
    AdmissionCrawlOutcome,
    crawl_and_upsert_admission,
    run_biyearly_admission,
)
from fujisawa_platform.etl.config import EtlConfig
from fujisawa_platform.etl.facility_resolver_builder import build_facility_resolver
from fujisawa_platform.etl.half_yearly_facility import (
    FacilityCrawlOutcome,
    crawl_and_replace_facilities,
    run_half_yearly_facility,
)
from fujisawa_platform.etl.monthly_vacancy import (
    MonthlyVacancyOutcome,
    crawl_and_upsert_vacancy,
    run_monthly_vacancy,
)
from fujisawa_platform.etl.pdf_archive import (
    GcsArchive,
    LocalArchive,
    NullArchive,
    PdfArchive,
    build_archive_from_config,
)
from fujisawa_platform.etl.weekly_crawl import (
    CrawlOutcome,
    crawl_and_index,
    run_weekly_crawl,
)
from fujisawa_platform.etl.yearly_navi import (
    NaviCrawlOutcome,
    crawl_and_index_navi,
    run_yearly_navi,
)

__all__ = [
    "AdmissionCrawlOutcome",
    "CrawlOutcome",
    "EtlConfig",
    "EtlRunResult",
    "FacilityCrawlOutcome",
    "GcsArchive",
    "LocalArchive",
    "MonthlyVacancyOutcome",
    "NaviCrawlOutcome",
    "NullArchive",
    "PdfArchive",
    "build_archive_from_config",
    "build_facility_resolver",
    "crawl_and_index",
    "crawl_and_index_navi",
    "crawl_and_replace_facilities",
    "crawl_and_upsert_admission",
    "crawl_and_upsert_vacancy",
    "run_biyearly_admission",
    "run_etl_job",
    "run_half_yearly_facility",
    "run_monthly_vacancy",
    "run_weekly_crawl",
    "run_yearly_navi",
]
