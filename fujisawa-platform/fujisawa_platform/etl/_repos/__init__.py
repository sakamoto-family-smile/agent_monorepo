"""ETL 用の Repository 群 (テーブル単位の薄い CRUD 抽象)。

`knowledge_base.PgvectorStore` と同じ立ち位置だが、こちらは ETL 内部用で
consumer 側 (LINE bot / 保活) からは直接見えない (etl/__init__ から re-export しない)。
"""

from fujisawa_platform.etl._repos.admission import AdmissionRepo, AdmissionResultRecord
from fujisawa_platform.etl._repos.etl_runs import EtlRunRecord, EtlRunsRepo
from fujisawa_platform.etl._repos.facilities import FacilitiesRepo, FacilityRecord
from fujisawa_platform.etl._repos.pdf_documents import (
    PdfDocumentRecord,
    PdfDocumentsRepo,
)
from fujisawa_platform.etl._repos.vacancy import (
    ApplicationRepo,
    ApplicationSnapshotRecord,
    VacancyRepo,
    VacancySnapshotRecord,
)

__all__ = [
    "AdmissionRepo",
    "AdmissionResultRecord",
    "ApplicationRepo",
    "ApplicationSnapshotRecord",
    "EtlRunRecord",
    "EtlRunsRepo",
    "FacilitiesRepo",
    "FacilityRecord",
    "PdfDocumentRecord",
    "PdfDocumentsRepo",
    "VacancyRepo",
    "VacancySnapshotRecord",
]
