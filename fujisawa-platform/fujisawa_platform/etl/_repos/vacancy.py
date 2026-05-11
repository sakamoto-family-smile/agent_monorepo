"""VacancyRepo + ApplicationRepo: 月次 snapshot テーブルへの薄い CRUD。

PK は両テーブルとも `(facility_id, year_month, age_class)`。
`monthly_vacancy_etl` が同 Job 内で両方を書き込む (proposal 0003 §4.5.4)。

整合性 (proposal 0003 §4.5.5):
- `year_month` で行が分離されているので、partial insert 中も既存月の整合性は保たれる
- 同一 PDF を再 run しても UPSERT で冪等
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:  # pragma: no cover
    import asyncpg


_YEAR_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _validate_year_month(value: str) -> str:
    if not _YEAR_MONTH_RE.match(value):
        raise ValueError(f"year_month must be 'YYYY-MM' format, got {value!r}")
    return value


class VacancySnapshotRecord(BaseModel):
    """`vacancy_snapshots` テーブル 1 行のモデル。"""

    model_config = ConfigDict(frozen=True)

    facility_id: str = Field(min_length=1)
    year_month: str  # 'YYYY-MM'
    age_class: int = Field(ge=0, le=5)
    vacancies: int = Field(ge=0)
    snapshot_date: date  # PDF 掲載日
    source_pdf_url: str
    fetched_at: datetime
    schema_version: str = "v1"

    @field_validator("year_month")
    @classmethod
    def _year_month(cls, v: str) -> str:
        return _validate_year_month(v)


class ApplicationSnapshotRecord(BaseModel):
    """`application_snapshots` テーブル 1 行のモデル。"""

    model_config = ConfigDict(frozen=True)

    facility_id: str = Field(min_length=1)
    year_month: str
    age_class: int = Field(ge=0, le=5)
    applicants: int = Field(ge=0)
    capacity: int = Field(ge=0)
    snapshot_date: date
    source_pdf_url: str
    fetched_at: datetime
    schema_version: str = "v1"

    @field_validator("year_month")
    @classmethod
    def _year_month(cls, v: str) -> str:
        return _validate_year_month(v)


class VacancyRepo:
    """`vacancy_snapshots` テーブルへのアクセス Repository。"""

    def __init__(self, *, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def upsert_many(self, records: list[VacancySnapshotRecord]) -> int:
        if not records:
            return 0
        async with self._pool.acquire() as conn:
            for record in records:
                await conn.execute(
                    """
                    INSERT INTO vacancy_snapshots (
                        facility_id, year_month, age_class, vacancies,
                        snapshot_date, source_pdf_url, fetched_at, schema_version
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (facility_id, year_month, age_class) DO UPDATE SET
                        vacancies = EXCLUDED.vacancies,
                        snapshot_date = EXCLUDED.snapshot_date,
                        source_pdf_url = EXCLUDED.source_pdf_url,
                        fetched_at = EXCLUDED.fetched_at,
                        schema_version = EXCLUDED.schema_version
                    """,
                    record.facility_id,
                    record.year_month,
                    record.age_class,
                    record.vacancies,
                    record.snapshot_date,
                    record.source_pdf_url,
                    record.fetched_at,
                    record.schema_version,
                )
        return len(records)

    async def count(self, *, year_month: str | None = None) -> int:
        async with self._pool.acquire() as conn:
            if year_month is not None:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS c FROM vacancy_snapshots WHERE year_month = $1",
                    year_month,
                )
            else:
                row = await conn.fetchrow("SELECT COUNT(*) AS c FROM vacancy_snapshots")
        if row is None:
            return 0
        return int(row["c"])


class ApplicationRepo:
    """`application_snapshots` テーブルへのアクセス Repository。"""

    def __init__(self, *, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def upsert_many(self, records: list[ApplicationSnapshotRecord]) -> int:
        if not records:
            return 0
        async with self._pool.acquire() as conn:
            for record in records:
                await conn.execute(
                    """
                    INSERT INTO application_snapshots (
                        facility_id, year_month, age_class, applicants, capacity,
                        snapshot_date, source_pdf_url, fetched_at, schema_version
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (facility_id, year_month, age_class) DO UPDATE SET
                        applicants = EXCLUDED.applicants,
                        capacity = EXCLUDED.capacity,
                        snapshot_date = EXCLUDED.snapshot_date,
                        source_pdf_url = EXCLUDED.source_pdf_url,
                        fetched_at = EXCLUDED.fetched_at,
                        schema_version = EXCLUDED.schema_version
                    """,
                    record.facility_id,
                    record.year_month,
                    record.age_class,
                    record.applicants,
                    record.capacity,
                    record.snapshot_date,
                    record.source_pdf_url,
                    record.fetched_at,
                    record.schema_version,
                )
        return len(records)

    async def count(self, *, year_month: str | None = None) -> int:
        async with self._pool.acquire() as conn:
            if year_month is not None:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS c FROM application_snapshots WHERE year_month = $1",
                    year_month,
                )
            else:
                row = await conn.fetchrow("SELECT COUNT(*) AS c FROM application_snapshots")
        if row is None:
            return 0
        return int(row["c"])


__all__ = [
    "ApplicationRepo",
    "ApplicationSnapshotRecord",
    "VacancyRepo",
    "VacancySnapshotRecord",
]
