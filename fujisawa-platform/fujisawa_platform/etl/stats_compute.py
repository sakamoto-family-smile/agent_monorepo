"""競争度集計のロジック (pure 関数)。

`admission_results` のリスト → `CompetitionStatsRecord` を生成する。
DB 接続不要なので、ETL Job と独立に単体テスト可能。

集計ルール (proposal 0005 §9.5 / 調査ノート §A2-2 のハイブリッドモデル):
- ratio = applicants_at_deadline / capacity (各年、1 次のみ)
- avg_ratio_3y = 直近 3 年の ratio 平均 (None 値は除外)
- competition_level: 倍率 → '超人気' (2.0+) / '人気' (1.0+) / '比較的入りやすい' (< 1.0) / 'data_unavailable'
- trend: 最古 vs 最新の ratio から rising / stable / declining (10% 閾値)
- confidence: 有効データ年数 → high (3+) / medium (2) / low (1) / unknown (0)
- historical_minimum_index_2022: 令和 4 年 (2022) レコードの min_* が揃っていれば抽出
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from statistics import mean

from fujisawa_platform.etl._repos.admission import AdmissionResultRecord
from fujisawa_platform.etl._repos.competition_stats import (
    CompetitionStatsRecord,
    HistoricalMinimumIndex,
    YearlyCompetitionEntry,
)

_RECENT_YEARS_FOR_AVG = 3
_TREND_THRESHOLD = 0.10  # ±10% で rising / declining 判定
_FIRST_ROUND = "1st"


def classify_level(ratio: float | None) -> str:
    """ratio (applicants / capacity) → 競争度ラベル。"""
    if ratio is None:
        return "data_unavailable"
    if ratio >= 2.0:
        return "超人気"
    if ratio >= 1.0:
        return "人気"
    return "比較的入りやすい"


def classify_trend(ratios: list[float | None]) -> str | None:
    """年次の ratio 列 (古い → 新しい順) から trend を判定。

    2 点未満なら None。None 値は skip して残り点数で判定。
    """
    valid = [r for r in ratios if r is not None]
    if len(valid) < 2:
        return None
    delta = (valid[-1] - valid[0]) / valid[0] if valid[0] > 0 else 0.0
    if delta > _TREND_THRESHOLD:
        return "rising"
    if delta < -_TREND_THRESHOLD:
        return "declining"
    return "stable"


def confidence_from_years(year_count: int) -> str:
    if year_count >= 3:
        return "high"
    if year_count == 2:
        return "medium"
    if year_count == 1:
        return "low"
    return "unknown"


def compute_competition_stats(
    *,
    facility_id: str,
    age_class: int,
    admissions: list[AdmissionResultRecord],
    now: Callable[[], datetime] | None = None,
) -> CompetitionStatsRecord:
    """1 (facility_id, age_class) について `CompetitionStatsRecord` を生成。

    Args:
        facility_id / age_class: 集計キー。
        admissions: その施設・年齢クラスの全 `AdmissionResultRecord` (年度・1次/2次 混在可)。
            1 次のみ抽出して計算する。
        now: last_updated 用 (テスト差し替え可能)。
    """
    _now = now or _utcnow

    # 1 次のみ、年度昇順
    first_round = sorted(
        (r for r in admissions if r.round == _FIRST_ROUND),
        key=lambda r: r.year,
    )

    history: list[YearlyCompetitionEntry] = []
    based_on: list[str] = []
    seen_urls: set[str] = set()
    for rec in first_round:
        ratio = _compute_ratio(rec.applicants_at_deadline, rec.capacity)
        history.append(
            YearlyCompetitionEntry(
                year=rec.year,
                ratio=ratio,
                vacancy_after_1st=rec.vacancy_after,
                level=classify_level(ratio),
            )
        )
        if rec.source_pdf_url not in seen_urls:
            based_on.append(rec.source_pdf_url)
            seen_urls.add(rec.source_pdf_url)

    # 直近 3 年から avg_ratio_3y
    recent_ratios = [e.ratio for e in history[-_RECENT_YEARS_FOR_AVG:]]
    valid_recent = [r for r in recent_ratios if r is not None]
    avg_ratio_3y = mean(valid_recent) if valid_recent else None

    competition_level = classify_level(avg_ratio_3y)
    trend = classify_trend(recent_ratios)
    confidence = confidence_from_years(len(valid_recent))

    historical_minimum = _extract_historical_minimum_2022(first_round)

    return CompetitionStatsRecord(
        facility_id=facility_id,
        age_class=age_class,
        history=history,
        avg_ratio_3y=avg_ratio_3y,
        competition_level=competition_level,
        trend=trend,
        confidence=confidence,
        historical_minimum_index_2022=historical_minimum,
        based_on=based_on,
        last_updated=_now(),
    )


def _compute_ratio(applicants: int | None, capacity: int | None) -> float | None:
    if applicants is None or capacity is None or capacity <= 0:
        return None
    return applicants / capacity


def _extract_historical_minimum_2022(
    admissions: list[AdmissionResultRecord],
) -> HistoricalMinimumIndex | None:
    """令和 4 年 (2022) のレコードに min_* が揃っていれば HistoricalMinimumIndex を作る。"""
    for rec in admissions:
        if rec.year != 2022:
            continue
        if (
            rec.min_basic_score is not None
            and rec.min_priority is not None
            and rec.min_coordination_score is not None
            and rec.min_index_notation is not None
        ):
            return HistoricalMinimumIndex(
                basic=rec.min_basic_score,
                priority=rec.min_priority,
                coord=rec.min_coordination_score,
                notation=rec.min_index_notation,
                source_pdf_url=rec.source_pdf_url,
            )
    return None


def _utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "classify_level",
    "classify_trend",
    "compute_competition_stats",
    "confidence_from_years",
]
