"""vacancy_parser のテスト。

`PdfTable` (Docling 抽出) → list[VacancySnapshot/ApplicationSnapshot] への変換を検証する。

空き状況 PDF の典型形:
- 列: 施設名 + 0歳児/1歳児/.../5歳児 (各セルが空き数)

申込状況 PDF の典型形:
- 列: 施設名 + (0歳児定員, 0歳児申込) × 6
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from fujisawa_platform.etl.vacancy_parser import (
    parse_application_table,
    parse_vacancy_table,
)
from fujisawa_platform.pdf_pipeline import PdfTable
from fujisawa_platform.resolver import FacilityResolver, ResolverEntry

_NOW = datetime(2026, 5, 11, 0, 0, tzinfo=UTC)
_SNAP_DATE = date(2026, 4, 1)
_VACANCY_URL = "https://example.com/akizyoukyou20260401.pdf"
_APP_URL = "https://example.com/mousikomizyoukyou20260401.pdf"


def _resolver() -> FacilityResolver:
    return FacilityResolver(
        [
            ResolverEntry(facility_id="kouritsu-aaa", canonical_name="藤沢保育園"),
            ResolverEntry(facility_id="kouritsu-bbb", canonical_name="辻堂保育園"),
        ]
    )


# ─────────────────────────────────────────────────────────────────────
# parse_vacancy_table (空き状況 PDF)
# ─────────────────────────────────────────────────────────────────────


class TestParseVacancyTable:
    def test_extracts_one_record_per_age_class(self) -> None:
        """1 行 1 施設 × 6 age_class カラム → 最大 6 件 VacancySnapshotRecord。"""
        table = PdfTable(
            headers=[
                "施設名",
                "0歳児",
                "1歳児",
                "2歳児",
                "3歳児",
                "4歳児",
                "5歳児",
            ],
            rows=[
                ["藤沢保育園", "0", "1", "2", "3", "4", "5"],
            ],
        )

        records = parse_vacancy_table(
            table=table,
            year_month="2026-04",
            snapshot_date=_SNAP_DATE,
            source_pdf_url=_VACANCY_URL,
            fetched_at=_NOW,
            resolver=_resolver(),
        )

        assert len(records) == 6
        assert {r.age_class for r in records} == {0, 1, 2, 3, 4, 5}
        assert {r.facility_id for r in records} == {"kouritsu-aaa"}
        assert all(r.year_month == "2026-04" for r in records)
        assert all(r.source_pdf_url == _VACANCY_URL for r in records)
        # 値の対応
        by_age = {r.age_class: r.vacancies for r in records}
        assert by_age == {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5}

    def test_skips_empty_cells(self) -> None:
        """`-` / 空セルは記録しない (1 行 1 age_class の欠落)。"""
        table = PdfTable(
            headers=["施設名", "0歳児", "1歳児"],
            rows=[["藤沢保育園", "3", "-"]],
        )
        records = parse_vacancy_table(
            table=table,
            year_month="2026-04",
            snapshot_date=_SNAP_DATE,
            source_pdf_url=_VACANCY_URL,
            fetched_at=_NOW,
            resolver=_resolver(),
        )
        assert len(records) == 1
        assert records[0].age_class == 0
        assert records[0].vacancies == 3

    def test_skips_row_when_facility_not_resolved(self) -> None:
        table = PdfTable(
            headers=["施設名", "0歳児"],
            rows=[
                ["全く別の施設名XYZ", "3"],
                ["辻堂保育園", "2"],
            ],
        )
        records = parse_vacancy_table(
            table=table,
            year_month="2026-04",
            snapshot_date=_SNAP_DATE,
            source_pdf_url=_VACANCY_URL,
            fetched_at=_NOW,
            resolver=_resolver(),
        )
        assert len(records) == 1
        assert records[0].facility_id == "kouritsu-bbb"

    def test_negative_or_invalid_cell_skipped(self) -> None:
        """負数 / 文字列セルは skip (validator が ValueError 上げる前に parser で除外)。"""
        table = PdfTable(
            headers=["施設名", "0歳児", "1歳児"],
            rows=[["藤沢保育園", "-1", "abc"]],
        )
        records = parse_vacancy_table(
            table=table,
            year_month="2026-04",
            snapshot_date=_SNAP_DATE,
            source_pdf_url=_VACANCY_URL,
            fetched_at=_NOW,
            resolver=_resolver(),
        )
        assert records == []

    def test_returns_empty_when_no_facility_name_column(self) -> None:
        table = PdfTable(
            headers=["A", "B", "C"],
            rows=[["x", "1", "2"]],
        )
        records = parse_vacancy_table(
            table=table,
            year_month="2026-04",
            snapshot_date=_SNAP_DATE,
            source_pdf_url=_VACANCY_URL,
            fetched_at=_NOW,
            resolver=_resolver(),
        )
        assert records == []


# ─────────────────────────────────────────────────────────────────────
# parse_application_table (申込状況 PDF)
# ─────────────────────────────────────────────────────────────────────


class TestParseApplicationTable:
    def test_extracts_applicants_and_capacity(self) -> None:
        table = PdfTable(
            headers=[
                "施設名",
                "0歳児定員",
                "0歳児申込",
                "1歳児定員",
                "1歳児申込",
            ],
            rows=[
                ["藤沢保育園", "12", "30", "18", "20"],
            ],
        )
        records = parse_application_table(
            table=table,
            year_month="2026-04",
            snapshot_date=_SNAP_DATE,
            source_pdf_url=_APP_URL,
            fetched_at=_NOW,
            resolver=_resolver(),
        )

        assert len(records) == 2
        by_age = {r.age_class: r for r in records}
        assert by_age[0].applicants == 30
        assert by_age[0].capacity == 12
        assert by_age[1].applicants == 20
        assert by_age[1].capacity == 18
        assert all(r.facility_id == "kouritsu-aaa" for r in records)

    def test_skips_age_class_with_missing_values(self) -> None:
        """`定員` か `申込` のどちらかが欠けた age_class は skip。"""
        table = PdfTable(
            headers=[
                "施設名",
                "0歳児定員",
                "0歳児申込",
                "1歳児定員",
                "1歳児申込",
            ],
            rows=[["藤沢保育園", "12", "30", "", ""]],
        )
        records = parse_application_table(
            table=table,
            year_month="2026-04",
            snapshot_date=_SNAP_DATE,
            source_pdf_url=_APP_URL,
            fetched_at=_NOW,
            resolver=_resolver(),
        )
        assert len(records) == 1
        assert records[0].age_class == 0

    def test_skips_row_when_facility_not_resolved(self) -> None:
        table = PdfTable(
            headers=["施設名", "0歳児定員", "0歳児申込"],
            rows=[
                ["未知保育園", "12", "30"],
                ["辻堂保育園", "12", "30"],
            ],
        )
        records = parse_application_table(
            table=table,
            year_month="2026-04",
            snapshot_date=_SNAP_DATE,
            source_pdf_url=_APP_URL,
            fetched_at=_NOW,
            resolver=_resolver(),
        )
        assert len(records) == 1
        assert records[0].facility_id == "kouritsu-bbb"

    def test_handles_2_to_5_age_classes(self) -> None:
        table = PdfTable(
            headers=[
                "施設名",
                "2歳児定員",
                "2歳児申込",
                "5歳児定員",
                "5歳児申込",
            ],
            rows=[["藤沢保育園", "20", "15", "20", "0"]],
        )
        records = parse_application_table(
            table=table,
            year_month="2026-04",
            snapshot_date=_SNAP_DATE,
            source_pdf_url=_APP_URL,
            fetched_at=_NOW,
            resolver=_resolver(),
        )
        ages = sorted(r.age_class for r in records)
        assert ages == [2, 5]
