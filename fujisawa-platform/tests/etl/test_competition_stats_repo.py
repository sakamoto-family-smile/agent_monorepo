"""CompetitionStatsRepo のテスト。

`competition_stats` テーブルへの UPSERT (by (facility_id, age_class)) を mock asyncpg.Pool
で検証する。JSONB フィールド (history / based_on / historical_minimum_index_2022) は
`json.dumps(..., ensure_ascii=False)` で文字列バインドする。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from fujisawa_platform.etl._repos.competition_stats import (
    CompetitionStatsRecord,
    CompetitionStatsRepo,
    HistoricalMinimumIndex,
    YearlyCompetitionEntry,
)
from tests.etl._stubs import StubConnection, StubPool

_NOW = datetime(2026, 5, 12, 0, 0, tzinfo=UTC)


def _record(
    *,
    facility_id: str = "kouritsu-aaa",
    age_class: int = 0,
    history: list[YearlyCompetitionEntry] | None = None,
    avg_ratio_3y: float | None = 1.8,
    competition_level: str | None = "人気",
    trend: str | None = "stable",
    confidence: str = "high",
    historical_minimum_index_2022: HistoricalMinimumIndex | None = None,
    based_on: list[str] | None = None,
) -> CompetitionStatsRecord:
    return CompetitionStatsRecord(
        facility_id=facility_id,
        age_class=age_class,
        history=history
        or [
            YearlyCompetitionEntry(year=2024, ratio=2.5, vacancy_after_1st=0, level="超人気"),
            YearlyCompetitionEntry(year=2025, ratio=2.0, vacancy_after_1st=0, level="人気"),
            YearlyCompetitionEntry(
                year=2026, ratio=1.0, vacancy_after_1st=2, level="比較的入りやすい"
            ),
        ],
        avg_ratio_3y=avg_ratio_3y,
        competition_level=competition_level,
        trend=trend,
        confidence=confidence,
        historical_minimum_index_2022=historical_minimum_index_2022,
        based_on=based_on or ["https://example.com/r6.pdf", "https://example.com/r7.pdf"],
        last_updated=_NOW,
    )


class TestUpsertMany:
    @pytest.mark.asyncio
    async def test_upsert_one_per_record(self) -> None:
        conn = StubConnection()
        repo = CompetitionStatsRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        await repo.upsert_many([_record(age_class=0), _record(age_class=1)])

        assert len(conn.executed) == 2
        for sql, _ in conn.executed:
            assert "INSERT INTO competition_stats" in sql
            assert "ON CONFLICT (facility_id, age_class) DO UPDATE" in sql

    @pytest.mark.asyncio
    async def test_serializes_jsonb_fields(self) -> None:
        """history / based_on / historical_minimum_index_2022 は jsonb 文字列。"""
        conn = StubConnection()
        repo = CompetitionStatsRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        rec = _record(
            historical_minimum_index_2022=HistoricalMinimumIndex(
                basic=10,
                priority="F",
                coord=11,
                notation="10F11※",
                source_pdf_url="https://example.com/r4.pdf",
            ),
        )
        await repo.upsert_many([rec])

        _, args = conn.executed[0]
        # 列順: facility_id, age_class, history, avg_ratio_3y, competition_level,
        #       trend, confidence, historical_minimum_index_2022, based_on,
        #       last_updated, schema_version
        assert args[0] == "kouritsu-aaa"
        assert args[1] == 0
        # history は JSON 文字列
        history = json.loads(args[2])
        assert len(history) == 3
        assert history[0]["year"] == 2024
        assert history[0]["level"] == "超人気"
        # historical_minimum_index_2022
        hmi = json.loads(args[7])
        assert hmi["priority"] == "F"
        assert hmi["notation"] == "10F11※"
        # based_on
        based = json.loads(args[8])
        assert based == ["https://example.com/r6.pdf", "https://example.com/r7.pdf"]

    @pytest.mark.asyncio
    async def test_historical_minimum_can_be_none(self) -> None:
        """令和 4 年以外の年度は historical_minimum_index_2022 が None で OK。"""
        conn = StubConnection()
        repo = CompetitionStatsRepo(pool=StubPool(conn))  # type: ignore[arg-type]

        await repo.upsert_many([_record(historical_minimum_index_2022=None)])
        _, args = conn.executed[0]
        assert args[7] is None  # None は jsonb cast せず NULL バインド

    @pytest.mark.asyncio
    async def test_empty_list_is_noop(self) -> None:
        conn = StubConnection()
        repo = CompetitionStatsRepo(pool=StubPool(conn))  # type: ignore[arg-type]
        n = await repo.upsert_many([])
        assert n == 0
        assert conn.executed == []


class TestCount:
    @pytest.mark.asyncio
    async def test_count_total(self) -> None:
        conn = StubConnection(fetchrow_results=[{"c": 768}])
        repo = CompetitionStatsRepo(pool=StubPool(conn))  # type: ignore[arg-type]
        assert await repo.count() == 768

    @pytest.mark.asyncio
    async def test_count_returns_zero_when_no_row(self) -> None:
        conn = StubConnection(fetchrow_results=[None])
        repo = CompetitionStatsRepo(pool=StubPool(conn))  # type: ignore[arg-type]
        assert await repo.count() == 0


class TestRecordValidation:
    def test_confidence_required(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            CompetitionStatsRecord(
                facility_id="x",
                age_class=0,
                history=[],
                confidence="invalid",
                based_on=[],
                last_updated=_NOW,
            )

    def test_competition_level_validation(self) -> None:
        with pytest.raises(ValueError, match="competition_level"):
            CompetitionStatsRecord(
                facility_id="x",
                age_class=0,
                history=[],
                confidence="high",
                competition_level="圏外",  # 未定義値
                based_on=[],
                last_updated=_NOW,
            )

    def test_trend_validation(self) -> None:
        with pytest.raises(ValueError, match="trend"):
            CompetitionStatsRecord(
                facility_id="x",
                age_class=0,
                history=[],
                confidence="high",
                trend="boom",
                based_on=[],
                last_updated=_NOW,
            )

    def test_age_class_range(self) -> None:
        with pytest.raises(ValueError, match="age_class"):
            CompetitionStatsRecord(
                facility_id="x",
                age_class=99,
                history=[],
                confidence="high",
                based_on=[],
                last_updated=_NOW,
            )

    def test_frozen(self) -> None:
        rec = _record()
        with pytest.raises(Exception):
            rec.avg_ratio_3y = 99.0  # type: ignore[misc]


class TestHistoricalMinimumIndex:
    def test_basic_construction(self) -> None:
        hmi = HistoricalMinimumIndex(
            basic=10, priority="F", coord=11, notation="10F11", source_pdf_url="https://x"
        )
        assert hmi.basic == 10
        assert hmi.priority == "F"

    def test_priority_pattern(self) -> None:
        """priority は単一英大文字 (A〜K のうち H なし)。"""
        with pytest.raises(ValueError):
            HistoricalMinimumIndex(
                basic=10,
                priority="FG",  # 2 文字 NG
                coord=11,
                notation="x",
                source_pdf_url="https://x",
            )
