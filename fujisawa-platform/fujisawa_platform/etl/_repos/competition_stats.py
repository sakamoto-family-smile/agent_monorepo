"""CompetitionStatsRepo: `competition_stats` テーブルへの薄い CRUD。

書き込み元: `monthly_stats_compute` (Phase 4-2f、外部 fetch なし)。
PK: `(facility_id, age_class)`。UPSERT で月次集計を上書きする (proposal 0003 §4.5.5)。

JSONB フィールド:
- `history`: 年次のリスト (`[{year, ratio, vacancy_after_1st, level}]`)
- `historical_minimum_index_2022`: 令和 4 年最低指数 (`{basic, priority, coord, notation, source_pdf_url}`)
- `based_on`: 集計に使った PDF URL のリスト
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:  # pragma: no cover
    import asyncpg


_ALLOWED_LEVELS = ("超人気", "人気", "比較的入りやすい", "data_unavailable")
_ALLOWED_TRENDS = ("rising", "stable", "declining")
_ALLOWED_CONFIDENCE = ("high", "medium", "low", "unknown")


class YearlyCompetitionEntry(BaseModel):
    """`history` JSONB 配列の 1 要素。"""

    model_config = ConfigDict(frozen=True)

    year: int
    ratio: float | None  # applicants / capacity。データなしは None
    vacancy_after_1st: int | None  # 1 次後の利用枠残
    level: str  # その年の judged level


class HistoricalMinimumIndex(BaseModel):
    """令和 4 年限定の最低指数情報 (proposal 0005 §9.5 ハイブリッドモデル)。"""

    model_config = ConfigDict(frozen=True)

    basic: int
    priority: str = Field(pattern=r"^[A-GIJK]$")  # H なし、A-K のうち
    coord: int
    notation: str
    source_pdf_url: str


class CompetitionStatsRecord(BaseModel):
    """`competition_stats` テーブル 1 行のモデル。"""

    model_config = ConfigDict(frozen=True)

    facility_id: str = Field(min_length=1)
    age_class: int = Field(ge=0, le=5)
    history: list[YearlyCompetitionEntry]
    avg_ratio_3y: float | None = None
    competition_level: str | None = None
    trend: str | None = None
    confidence: str
    historical_minimum_index_2022: HistoricalMinimumIndex | None = None
    based_on: list[str]
    last_updated: datetime
    schema_version: str = "v1"

    @field_validator("competition_level")
    @classmethod
    def _level(cls, v: str | None) -> str | None:
        if v is not None and v not in _ALLOWED_LEVELS:
            raise ValueError(f"competition_level must be one of {_ALLOWED_LEVELS}, got {v!r}")
        return v

    @field_validator("trend")
    @classmethod
    def _trend(cls, v: str | None) -> str | None:
        if v is not None and v not in _ALLOWED_TRENDS:
            raise ValueError(f"trend must be one of {_ALLOWED_TRENDS}, got {v!r}")
        return v

    @field_validator("confidence")
    @classmethod
    def _confidence(cls, v: str) -> str:
        if v not in _ALLOWED_CONFIDENCE:
            raise ValueError(f"confidence must be one of {_ALLOWED_CONFIDENCE}, got {v!r}")
        return v


class CompetitionStatsRepo:
    """`competition_stats` テーブルへのアクセス Repository。"""

    def __init__(self, *, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def upsert_many(self, records: list[CompetitionStatsRecord]) -> int:
        if not records:
            return 0
        async with self._pool.acquire() as conn:
            for record in records:
                await conn.execute(
                    """
                    INSERT INTO competition_stats (
                        facility_id, age_class, history,
                        avg_ratio_3y, competition_level, trend, confidence,
                        historical_minimum_index_2022, based_on,
                        last_updated, schema_version
                    ) VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7,
                              $8::jsonb, $9::jsonb, $10, $11)
                    ON CONFLICT (facility_id, age_class) DO UPDATE SET
                        history = EXCLUDED.history,
                        avg_ratio_3y = EXCLUDED.avg_ratio_3y,
                        competition_level = EXCLUDED.competition_level,
                        trend = EXCLUDED.trend,
                        confidence = EXCLUDED.confidence,
                        historical_minimum_index_2022 = EXCLUDED.historical_minimum_index_2022,
                        based_on = EXCLUDED.based_on,
                        last_updated = EXCLUDED.last_updated,
                        schema_version = EXCLUDED.schema_version
                    """,
                    record.facility_id,
                    record.age_class,
                    _dump_history(record.history),
                    record.avg_ratio_3y,
                    record.competition_level,
                    record.trend,
                    record.confidence,
                    _dump_historical_minimum(record.historical_minimum_index_2022),
                    json.dumps(record.based_on, ensure_ascii=False),
                    record.last_updated,
                    record.schema_version,
                )
        return len(records)

    async def count(self) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT COUNT(*) AS c FROM competition_stats")
        if row is None:
            return 0
        return int(row["c"])


def _dump_history(history: list[YearlyCompetitionEntry]) -> str:
    return json.dumps(
        [
            {
                "year": e.year,
                "ratio": e.ratio,
                "vacancy_after_1st": e.vacancy_after_1st,
                "level": e.level,
            }
            for e in history
        ],
        ensure_ascii=False,
    )


def _dump_historical_minimum(hmi: HistoricalMinimumIndex | None) -> str | None:
    if hmi is None:
        return None
    return json.dumps(
        {
            "basic": hmi.basic,
            "priority": hmi.priority,
            "coord": hmi.coord,
            "notation": hmi.notation,
            "source_pdf_url": hmi.source_pdf_url,
        },
        ensure_ascii=False,
    )


def _row_to_record(row: Any) -> CompetitionStatsRecord:  # pragma: no cover — 将来の SELECT 用
    raw_history = row["history"]
    if isinstance(raw_history, str):
        raw_history = json.loads(raw_history)
    history = [
        YearlyCompetitionEntry(
            year=h["year"],
            ratio=h.get("ratio"),
            vacancy_after_1st=h.get("vacancy_after_1st"),
            level=h["level"],
        )
        for h in raw_history or []
    ]
    raw_based_on = row["based_on"]
    if isinstance(raw_based_on, str):
        raw_based_on = json.loads(raw_based_on)
    hmi_raw = row["historical_minimum_index_2022"]
    if isinstance(hmi_raw, str) and hmi_raw:
        hmi_raw = json.loads(hmi_raw)
    hmi = HistoricalMinimumIndex(**hmi_raw) if isinstance(hmi_raw, dict) else None
    return CompetitionStatsRecord(
        facility_id=row["facility_id"],
        age_class=row["age_class"],
        history=history,
        avg_ratio_3y=row["avg_ratio_3y"],
        competition_level=row["competition_level"],
        trend=row["trend"],
        confidence=row["confidence"],
        historical_minimum_index_2022=hmi,
        based_on=list(raw_based_on or []),
        last_updated=row["last_updated"],
        schema_version=row.get("schema_version", "v1"),
    )


__all__ = [
    "CompetitionStatsRecord",
    "CompetitionStatsRepo",
    "HistoricalMinimumIndex",
    "YearlyCompetitionEntry",
]
