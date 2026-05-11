"""admission_parser のテスト。

`PdfTable` (Docling 抽出) → list[AdmissionResultRecord] への変換を検証する。
4 月入所結果 PDF の典型形:
- 列: 施設名 + (0歳児定員, 0歳児申込, 0歳児利用枠) × 6 (0〜5 歳)
- 1 行 = 1 施設 → 1 行から最大 6 件の AdmissionResultRecord
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fujisawa_platform.etl.admission_parser import (
    parse_admission_table,
    parse_min_index_notation,
)
from fujisawa_platform.pdf_pipeline import PdfTable
from fujisawa_platform.resolver import FacilityResolver, NoMatchError, ResolverEntry

_NOW = datetime(2026, 5, 11, 0, 0, tzinfo=UTC)
_PDF_URL = "https://example.com/r8_admission_1st.pdf"


def _resolver() -> FacilityResolver:
    return FacilityResolver(
        [
            ResolverEntry(facility_id="kouritsu-aaa", canonical_name="藤沢保育園"),
            ResolverEntry(facility_id="kouritsu-bbb", canonical_name="辻堂保育園"),
        ],
        threshold=0.85,
    )


class TestParseAdmissionTable:
    def test_extracts_one_record_per_age_class(self) -> None:
        table = PdfTable(
            headers=[
                "施設名",
                "0歳児定員",
                "0歳児申込",
                "0歳児利用枠",
                "1歳児定員",
                "1歳児申込",
                "1歳児利用枠",
            ],
            rows=[
                ["藤沢保育園", "12", "30", "0", "18", "20", "1"],
            ],
        )

        records = parse_admission_table(
            table=table,
            year=2026,
            round="1st",
            source_pdf_url=_PDF_URL,
            as_of=_NOW,
            resolver=_resolver(),
        )

        # 0 歳と 1 歳の 2 件
        assert len(records) == 2
        r0 = next(r for r in records if r.age_class == 0)
        r1 = next(r for r in records if r.age_class == 1)
        assert r0.facility_id == "kouritsu-aaa"
        assert r0.capacity == 12
        assert r0.applicants_at_deadline == 30
        assert r0.vacancy_after == 0
        assert r1.capacity == 18
        assert r1.applicants_at_deadline == 20
        assert r1.vacancy_after == 1

    def test_resolves_facility_via_alias(self) -> None:
        """resolver の表記ゆれ吸収が機能する (中黒など)。"""
        resolver = FacilityResolver(
            [
                ResolverEntry(
                    facility_id="kouritsu-aaa",
                    canonical_name="藤沢市立藤沢保育園",
                    aliases=["藤沢保育園"],
                ),
            ],
        )
        table = PdfTable(
            headers=["施設名", "0歳児定員", "0歳児申込", "0歳児利用枠"],
            rows=[["藤沢保育園", "12", "30", "0"]],
        )
        records = parse_admission_table(
            table=table,
            year=2026,
            round="1st",
            source_pdf_url=_PDF_URL,
            as_of=_NOW,
            resolver=resolver,
        )
        assert records[0].facility_id == "kouritsu-aaa"

    def test_skips_row_when_facility_not_found(self) -> None:
        """resolver で解決できない施設名は skip (大幅な fuzzy ヒットも threshold 未満なら skip)。"""
        table = PdfTable(
            headers=["施設名", "0歳児定員", "0歳児申込", "0歳児利用枠"],
            rows=[
                ["全く別の保育園XYZ", "12", "30", "0"],
                ["藤沢保育園", "12", "30", "0"],
            ],
        )
        records = parse_admission_table(
            table=table,
            year=2026,
            round="1st",
            source_pdf_url=_PDF_URL,
            as_of=_NOW,
            resolver=_resolver(),
        )
        assert len(records) == 1
        assert records[0].facility_id == "kouritsu-aaa"

    def test_skips_age_class_with_missing_values(self) -> None:
        """空セルの age_class は skip (誤った 0 値で UPSERT してしまわない)。"""
        table = PdfTable(
            headers=[
                "施設名",
                "0歳児定員",
                "0歳児申込",
                "0歳児利用枠",
                "1歳児定員",
                "1歳児申込",
                "1歳児利用枠",
            ],
            rows=[
                # 0 歳は数値、1 歳は全部空 (該当クラスなし)
                ["藤沢保育園", "12", "30", "0", "", "", ""],
            ],
        )
        records = parse_admission_table(
            table=table,
            year=2026,
            round="1st",
            source_pdf_url=_PDF_URL,
            as_of=_NOW,
            resolver=_resolver(),
        )
        assert len(records) == 1
        assert records[0].age_class == 0

    def test_uses_resolved_facility_id_not_raw_name(self) -> None:
        """resolver が一致した entry の facility_id を採用 (raw 名は使わない)。"""
        table = PdfTable(
            headers=["施設名", "0歳児定員", "0歳児申込", "0歳児利用枠"],
            rows=[["辻堂保育園", "18", "25", "0"]],
        )
        records = parse_admission_table(
            table=table,
            year=2026,
            round="1st",
            source_pdf_url=_PDF_URL,
            as_of=_NOW,
            resolver=_resolver(),
        )
        assert records[0].facility_id == "kouritsu-bbb"

    def test_year_and_round_preserved(self) -> None:
        table = PdfTable(
            headers=["施設名", "0歳児定員", "0歳児申込", "0歳児利用枠"],
            rows=[["藤沢保育園", "12", "30", "0"]],
        )
        records = parse_admission_table(
            table=table,
            year=2024,
            round="2nd",
            source_pdf_url=_PDF_URL,
            as_of=_NOW,
            resolver=_resolver(),
        )
        assert records[0].year == 2024
        assert records[0].round == "2nd"
        assert records[0].source_pdf_url == _PDF_URL
        assert records[0].as_of == _NOW

    def test_returns_empty_when_no_facility_name_column(self) -> None:
        table = PdfTable(
            headers=["A", "B", "C"],
            rows=[["x", "y", "z"]],
        )
        records = parse_admission_table(
            table=table,
            year=2026,
            round="1st",
            source_pdf_url=_PDF_URL,
            as_of=_NOW,
            resolver=_resolver(),
        )
        assert records == []

    def test_handles_age_classes_2_to_5(self) -> None:
        """2 〜 5 歳のクラスも正しく抽出される。"""
        table = PdfTable(
            headers=[
                "施設名",
                "2歳児定員",
                "2歳児申込",
                "2歳児利用枠",
                "5歳児定員",
                "5歳児申込",
                "5歳児利用枠",
            ],
            rows=[["藤沢保育園", "20", "15", "5", "20", "0", "20"]],
        )
        records = parse_admission_table(
            table=table,
            year=2026,
            round="1st",
            source_pdf_url=_PDF_URL,
            as_of=_NOW,
            resolver=_resolver(),
        )
        age_classes = sorted(r.age_class for r in records)
        assert age_classes == [2, 5]
        five = next(r for r in records if r.age_class == 5)
        assert five.vacancy_after == 20


# ─────────────────────────────────────────────────────────────────────
# parse_min_index_notation (令和 4 年限定: 「10F11※」 → 構造化)
# ─────────────────────────────────────────────────────────────────────


class TestParseMinIndexNotation:
    def test_standard_notation(self) -> None:
        """`10F11` → basic=10, priority=F, coord=11。"""
        result = parse_min_index_notation("10F11")
        assert result is not None
        basic, priority, coord = result
        assert basic == 10
        assert priority == "F"
        assert coord == 11

    def test_with_marker_suffix(self) -> None:
        """`10F11※` → marker 込みでも parse できる。"""
        result = parse_min_index_notation("10F11※")
        assert result is not None
        basic, priority, coord = result
        assert basic == 10
        assert priority == "F"
        assert coord == 11

    @pytest.mark.parametrize(
        "marker",
        ["△", "○", "-", "＼"],
    )
    def test_non_indexable_markers_return_none(self, marker: str) -> None:
        """単独マーカー (内定者 1 / 定員空き / 空きなし / クラス無) は None。"""
        assert parse_min_index_notation(marker) is None

    def test_empty_returns_none(self) -> None:
        assert parse_min_index_notation("") is None

    def test_invalid_format_returns_none(self) -> None:
        assert parse_min_index_notation("not-a-score") is None

    def test_two_digit_priority_not_supported(self) -> None:
        """priority は 1 文字 (A〜K) のみ対応。"""
        assert parse_min_index_notation("10FG11") is None


# ─────────────────────────────────────────────────────────────────────
# NoMatchError は伝播せず skip される (上位のループで吸収済を確認)
# ─────────────────────────────────────────────────────────────────────


def test_resolver_no_match_is_swallowed() -> None:
    """parser は NoMatchError を上位に投げず、該当行を skip する。"""
    table = PdfTable(
        headers=["施設名", "0歳児定員", "0歳児申込", "0歳児利用枠"],
        rows=[["未知保育園", "12", "30", "0"]],
    )
    records = parse_admission_table(
        table=table,
        year=2026,
        round="1st",
        source_pdf_url=_PDF_URL,
        as_of=_NOW,
        resolver=_resolver(),
    )
    assert records == []

    # 直接 resolver を呼ぶと NoMatchError は上がる (parser 側で握りつぶしているだけ)
    with pytest.raises(NoMatchError):
        _resolver().resolve("未知保育園")
