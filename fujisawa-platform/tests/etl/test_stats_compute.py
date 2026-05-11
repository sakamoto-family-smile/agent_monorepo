"""stats_compute のテスト。

`admission_results` 入力 → `CompetitionStatsRecord` を生成する pure 関数。
DB 接続なしで全パターンを検証可能。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fujisawa_platform.etl._repos.admission import AdmissionResultRecord
from fujisawa_platform.etl.stats_compute import (
    classify_level,
    classify_trend,
    compute_competition_stats,
    confidence_from_years,
)

_NOW = datetime(2026, 5, 12, 0, 0, tzinfo=UTC)


def _admission(
    *,
    facility_id: str = "kouritsu-aaa",
    year: int,
    round: str = "1st",
    age_class: int = 0,
    applicants_at_deadline: int | None = 30,
    capacity: int | None = 12,
    vacancy_after: int | None = 0,
    source_pdf_url: str = "https://example.com/r.pdf",
    min_basic_score: int | None = None,
    min_priority: str | None = None,
    min_coordination_score: int | None = None,
    min_index_notation: str | None = None,
) -> AdmissionResultRecord:
    return AdmissionResultRecord(
        facility_id=facility_id,
        year=year,
        round=round,
        age_class=age_class,
        applicants_at_deadline=applicants_at_deadline,
        capacity=capacity,
        vacancy_after=vacancy_after,
        min_basic_score=min_basic_score,
        min_priority=min_priority,
        min_coordination_score=min_coordination_score,
        min_index_notation=min_index_notation,
        source_pdf_url=source_pdf_url,
        as_of=_NOW,
    )


# ─────────────────────────────────────────────────────────────────────
# classify_level (倍率 → 競争度ラベル)
# ─────────────────────────────────────────────────────────────────────


class TestClassifyLevel:
    @pytest.mark.parametrize(
        ("ratio", "expected"),
        [
            (2.5, "超人気"),  # 2.0+ → 超人気
            (2.0, "超人気"),
            (1.5, "人気"),  # 1.0 <= < 2.0 → 人気
            (1.0, "人気"),
            (0.9, "比較的入りやすい"),  # < 1.0
            (0.0, "比較的入りやすい"),
        ],
    )
    def test_classifies_by_ratio(self, ratio: float, expected: str) -> None:
        assert classify_level(ratio) == expected

    def test_none_returns_data_unavailable(self) -> None:
        assert classify_level(None) == "data_unavailable"


# ─────────────────────────────────────────────────────────────────────
# classify_trend (年次推移 → rising / stable / declining)
# ─────────────────────────────────────────────────────────────────────


class TestClassifyTrend:
    def test_rising(self) -> None:
        """最新が最古より 10% 以上高い → rising。"""
        # 古い → 新しい順
        assert classify_trend([1.0, 1.5, 1.5]) == "rising"

    def test_declining(self) -> None:
        assert classify_trend([2.0, 1.5, 1.0]) == "declining"

    def test_stable_within_10pct(self) -> None:
        assert classify_trend([1.5, 1.4, 1.55]) == "stable"

    def test_less_than_2_points_returns_none(self) -> None:
        """1 点だけでは trend 判定できない。"""
        assert classify_trend([1.5]) is None
        assert classify_trend([]) is None

    def test_ignores_none_entries(self) -> None:
        """None 値の年度はスキップして残りで判定。"""
        assert classify_trend([1.0, None, 1.5]) == "rising"

    def test_all_none_returns_none(self) -> None:
        assert classify_trend([None, None, None]) is None


# ─────────────────────────────────────────────────────────────────────
# confidence_from_years
# ─────────────────────────────────────────────────────────────────────


class TestConfidenceFromYears:
    @pytest.mark.parametrize(
        ("years", "expected"),
        [(3, "high"), (2, "medium"), (1, "low"), (0, "unknown"), (5, "high")],
    )
    def test_levels(self, years: int, expected: str) -> None:
        assert confidence_from_years(years) == expected


# ─────────────────────────────────────────────────────────────────────
# compute_competition_stats (本丸)
# ─────────────────────────────────────────────────────────────────────


class TestComputeCompetitionStats:
    def test_3_years_data_produces_high_confidence(self) -> None:
        """3 年分の 1 次データ → confidence=high、avg_ratio_3y + level/trend 計算。"""
        records = [
            _admission(year=2024, applicants_at_deadline=24, capacity=12),  # ratio 2.0
            _admission(year=2025, applicants_at_deadline=18, capacity=12),  # 1.5
            _admission(year=2026, applicants_at_deadline=12, capacity=12),  # 1.0
        ]
        result = compute_competition_stats(
            facility_id="kouritsu-aaa",
            age_class=0,
            admissions=records,
            now=lambda: _NOW,
        )

        assert result is not None
        assert result.facility_id == "kouritsu-aaa"
        assert result.age_class == 0
        assert result.confidence == "high"
        # avg = (2.0 + 1.5 + 1.0) / 3 = 1.5
        assert result.avg_ratio_3y == pytest.approx(1.5)
        assert result.competition_level == "人気"
        # 2.0 → 1.0 は declining
        assert result.trend == "declining"
        # history は 3 件、年次順
        assert len(result.history) == 3
        assert [h.year for h in result.history] == [2024, 2025, 2026]
        # based_on は重複なし
        assert len(result.based_on) == 1
        # historical_minimum_index_2022 は無い (min_* 未指定)
        assert result.historical_minimum_index_2022 is None

    def test_1_year_only_low_confidence(self) -> None:
        records = [_admission(year=2026, applicants_at_deadline=12, capacity=12)]
        result = compute_competition_stats(
            facility_id="kouritsu-aaa",
            age_class=0,
            admissions=records,
            now=lambda: _NOW,
        )
        assert result is not None
        assert result.confidence == "low"
        assert result.trend is None  # 1 点では trend 判定不可

    def test_no_data_returns_data_unavailable(self) -> None:
        result = compute_competition_stats(
            facility_id="kouritsu-aaa",
            age_class=0,
            admissions=[],
            now=lambda: _NOW,
        )
        assert result is not None
        assert result.confidence == "unknown"
        assert result.competition_level == "data_unavailable"
        assert result.avg_ratio_3y is None
        assert result.trend is None
        assert result.history == []
        assert result.based_on == []

    def test_filters_to_1st_round_only(self) -> None:
        """2 次入所結果 (round='2nd') は集計に含めない。"""
        records = [
            _admission(year=2026, round="1st", applicants_at_deadline=24, capacity=12),
            _admission(year=2026, round="2nd", applicants_at_deadline=4, capacity=2),
        ]
        result = compute_competition_stats(
            facility_id="kouritsu-aaa",
            age_class=0,
            admissions=records,
            now=lambda: _NOW,
        )
        assert result is not None
        assert len(result.history) == 1
        assert result.history[0].ratio == pytest.approx(2.0)

    def test_includes_only_last_3_years_in_avg(self) -> None:
        """avg_ratio_3y は **直近 3 年** のみ平均、history は全年保持。"""
        records = [
            _admission(year=2022, applicants_at_deadline=36, capacity=12),  # 3.0
            _admission(year=2023, applicants_at_deadline=24, capacity=12),  # 2.0
            _admission(year=2024, applicants_at_deadline=24, capacity=12),  # 2.0
            _admission(year=2025, applicants_at_deadline=18, capacity=12),  # 1.5
            _admission(year=2026, applicants_at_deadline=12, capacity=12),  # 1.0
        ]
        result = compute_competition_stats(
            facility_id="kouritsu-aaa",
            age_class=0,
            admissions=records,
            now=lambda: _NOW,
        )
        assert result is not None
        # 直近 3 年 = 2024, 2025, 2026 → avg = (2.0 + 1.5 + 1.0) / 3 = 1.5
        assert result.avg_ratio_3y == pytest.approx(1.5)
        # history は全 5 年保持
        assert len(result.history) == 5

    def test_extracts_historical_minimum_2022(self) -> None:
        """令和 4 年 (2022) のレコードに min_* があれば抽出。"""
        records = [
            _admission(
                year=2022,
                applicants_at_deadline=24,
                capacity=12,
                min_basic_score=10,
                min_priority="F",
                min_coordination_score=11,
                min_index_notation="10F11※",
            ),
            _admission(year=2026, applicants_at_deadline=12, capacity=12),
        ]
        result = compute_competition_stats(
            facility_id="kouritsu-aaa",
            age_class=0,
            admissions=records,
            now=lambda: _NOW,
        )
        assert result is not None
        assert result.historical_minimum_index_2022 is not None
        hmi = result.historical_minimum_index_2022
        assert hmi.basic == 10
        assert hmi.priority == "F"
        assert hmi.coord == 11
        assert hmi.notation == "10F11※"

    def test_handles_zero_capacity_as_none_ratio(self) -> None:
        """capacity=0 で割れない年度は ratio=None。"""
        records = [
            _admission(year=2026, applicants_at_deadline=5, capacity=0),
        ]
        result = compute_competition_stats(
            facility_id="kouritsu-aaa",
            age_class=0,
            admissions=records,
            now=lambda: _NOW,
        )
        assert result is not None
        assert result.history[0].ratio is None
        assert result.avg_ratio_3y is None  # 計算対象なし

    def test_handles_missing_applicants(self) -> None:
        """applicants_at_deadline が None なら ratio も None。"""
        records = [
            _admission(year=2026, applicants_at_deadline=None, capacity=12),
        ]
        result = compute_competition_stats(
            facility_id="kouritsu-aaa",
            age_class=0,
            admissions=records,
            now=lambda: _NOW,
        )
        assert result is not None
        assert result.history[0].ratio is None

    def test_deduplicates_based_on(self) -> None:
        """同じ source_pdf_url は based_on で重複させない。"""
        records = [
            _admission(year=2025, source_pdf_url="https://x/r7.pdf"),
            _admission(year=2026, source_pdf_url="https://x/r8.pdf"),
            _admission(
                year=2026, round="2nd", source_pdf_url="https://x/r8.pdf"
            ),  # 同 URL を 1 次/2 次 で共有想定
        ]
        result = compute_competition_stats(
            facility_id="kouritsu-aaa",
            age_class=0,
            admissions=records,
            now=lambda: _NOW,
        )
        assert result is not None
        # 2 次は除外されるが based_on は 1 次の 2 URL のみ
        assert sorted(result.based_on) == sorted(["https://x/r7.pdf", "https://x/r8.pdf"])
