"""AdmissionRepo: `admission_results` テーブルへの薄い CRUD。

主な書き込み元:
- `biyearly_admission_etl` (4 月入所結果 PDF、1 次・2 次)
- `wayback_backfill` (令和 4-6 年のバックフィル、Phase 4-2g)

PK: (facility_id, year, round, age_class) — 同一 facility × 年度 × 1 次/2 次 × 年齢
クラスを UPSERT。partial insert 中も既存 year_month は一貫性を保つ (proposal 0003 §4.5.5)。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:  # pragma: no cover
    import asyncpg


_ALLOWED_ROUNDS = ("1st", "2nd")


class AdmissionResultRecord(BaseModel):
    """`admission_results` テーブル 1 行のモデル。

    `min_*` フィールドは令和 4 年 (2022) のみ非 None (proposal 0005 §9.5 ハイブリッドモデル /
    調査ノート §A2-2)。それ以外の年は None。
    """

    model_config = ConfigDict(frozen=True)

    facility_id: str = Field(min_length=1)
    year: int
    round: str  # '1st' | '2nd'
    age_class: int = Field(ge=0, le=5)
    applicants_at_deadline: int | None = None
    capacity: int | None = None
    vacancy_after: int | None = None
    # 令和 4 年 (2022) 限定の最低内定指数情報
    min_basic_score: int | None = None
    min_priority: str | None = None  # 'A'..'K' (H なし)
    min_coordination_score: int | None = None
    min_index_notation: str | None = None  # '10F11※' 形式
    source_pdf_url: str
    as_of: datetime
    schema_version: str = "v1"

    @field_validator("round")
    @classmethod
    def _validate_round(cls, v: str) -> str:
        if v not in _ALLOWED_ROUNDS:
            raise ValueError(f"round must be one of {_ALLOWED_ROUNDS}, got {v!r}")
        return v


class AdmissionRepo:
    """`admission_results` テーブルへのアクセス Repository。"""

    def __init__(self, *, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def upsert_many(self, records: list[AdmissionResultRecord]) -> int:
        """複数行を UPSERT。同一 (facility_id, year, round, age_class) は上書き。

        Returns:
            UPSERT した件数。0 件渡された場合は 0 (DB アクセスなし)。
        """
        if not records:
            return 0
        async with self._pool.acquire() as conn:
            for record in records:
                await conn.execute(
                    """
                    INSERT INTO admission_results (
                        facility_id, year, round, age_class,
                        applicants_at_deadline, capacity, vacancy_after,
                        min_basic_score, min_priority,
                        min_coordination_score, min_index_notation,
                        source_pdf_url, as_of, schema_version
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9,
                              $10, $11, $12, $13, $14)
                    ON CONFLICT (facility_id, year, round, age_class) DO UPDATE SET
                        applicants_at_deadline = EXCLUDED.applicants_at_deadline,
                        capacity = EXCLUDED.capacity,
                        vacancy_after = EXCLUDED.vacancy_after,
                        min_basic_score = EXCLUDED.min_basic_score,
                        min_priority = EXCLUDED.min_priority,
                        min_coordination_score = EXCLUDED.min_coordination_score,
                        min_index_notation = EXCLUDED.min_index_notation,
                        source_pdf_url = EXCLUDED.source_pdf_url,
                        as_of = EXCLUDED.as_of,
                        schema_version = EXCLUDED.schema_version
                    """,
                    record.facility_id,
                    record.year,
                    record.round,
                    record.age_class,
                    record.applicants_at_deadline,
                    record.capacity,
                    record.vacancy_after,
                    record.min_basic_score,
                    record.min_priority,
                    record.min_coordination_score,
                    record.min_index_notation,
                    record.source_pdf_url,
                    record.as_of,
                    record.schema_version,
                )
        return len(records)

    async def count(self, *, year: int | None = None, round: str | None = None) -> int:
        """件数取得 (smoke / 監視用、year / round で絞り込み可能)。"""
        async with self._pool.acquire() as conn:
            if year is not None and round is not None:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS c FROM admission_results WHERE year = $1 AND round = $2",
                    year,
                    round,
                )
            elif year is not None:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS c FROM admission_results WHERE year = $1",
                    year,
                )
            else:
                row = await conn.fetchrow("SELECT COUNT(*) AS c FROM admission_results")
        if row is None:
            return 0
        return int(row["c"])


def _row_to_record(row: Any) -> AdmissionResultRecord:  # pragma: no cover — 将来の SELECT 用
    return AdmissionResultRecord(
        facility_id=row["facility_id"],
        year=row["year"],
        round=row["round"],
        age_class=row["age_class"],
        applicants_at_deadline=row["applicants_at_deadline"],
        capacity=row["capacity"],
        vacancy_after=row["vacancy_after"],
        min_basic_score=row["min_basic_score"],
        min_priority=row["min_priority"],
        min_coordination_score=row["min_coordination_score"],
        min_index_notation=row["min_index_notation"],
        source_pdf_url=row["source_pdf_url"],
        as_of=row["as_of"],
        schema_version=row.get("schema_version", "v1"),
    )


__all__ = ["AdmissionRepo", "AdmissionResultRecord"]
