"""min_index_parser のテスト。

令和 4 年限定の `r4-4nyuusyonaiteisisuu.pdf` (3 ページ、120+ 施設) の表を
施設×年齢クラス別に分解し、各セルから `MinIndexEntry` を抽出する parser。

セル形式 (調査ノート §A2-2):
- `10F11` 形式 → 基礎点=10、優先順位=F、調整=11
- `※` 付加 → 同点時の細目: 市民税 / 認可外期間 / 待機期間 (本 PR では notation に保持)
- `△` → 内定者 1 名 (個人情報保護で非公開)
- `○` → 定員に空きあり
- `-` / `−` → 空きなし
- `＼` → クラスなし
"""

from __future__ import annotations

from datetime import UTC, datetime

from fujisawa_platform.etl.min_index_parser import (
    MinIndexEntry,
    parse_min_index_table,
)
from fujisawa_platform.pdf_pipeline import PdfTable
from fujisawa_platform.resolver import FacilityResolver, ResolverEntry

_NOW = datetime(2026, 5, 12, 0, 0, tzinfo=UTC)
_SOURCE = "https://example.com/r4-4nyuusyonaiteisisuu.pdf"


def _resolver() -> FacilityResolver:
    return FacilityResolver(
        [
            ResolverEntry(facility_id="kouritsu-aaa", canonical_name="藤沢保育園"),
            ResolverEntry(facility_id="kouritsu-bbb", canonical_name="辻堂保育園"),
        ]
    )


# ─────────────────────────────────────────────────────────────────────
# parse_min_index_table
# ─────────────────────────────────────────────────────────────────────


class TestParseMinIndexTable:
    def test_extracts_entries_per_facility_and_age(self) -> None:
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
                # 0/1 歳に min_index、2 歳は空き / 5 歳はクラスなし
                ["藤沢保育園", "10F11", "12F8", "○", "○", "-", "＼"],
                ["辻堂保育園", "△", "9G5※", "8E10", "-", "-", "○"],
            ],
        )

        entries = parse_min_index_table(
            table=table,
            source_pdf_url=_SOURCE,
            resolver=_resolver(),
        )

        # 藤沢: 0歳, 1歳 (2 件) / 辻堂: 1歳, 2歳 (2 件) = 4 件
        assert len(entries) == 4
        by_facility_age = {(e.facility_id, e.age_class): e for e in entries}

        fuji_0 = by_facility_age[("kouritsu-aaa", 0)]
        assert isinstance(fuji_0, MinIndexEntry)
        assert fuji_0.basic == 10
        assert fuji_0.priority == "F"
        assert fuji_0.coord == 11
        assert fuji_0.notation == "10F11"
        assert fuji_0.source_pdf_url == _SOURCE

        # 辻堂 1歳児は `9G5※` → notation は ※ 込みで保持
        tuji_1 = by_facility_age[("kouritsu-bbb", 1)]
        assert tuji_1.basic == 9
        assert tuji_1.priority == "G"
        assert tuji_1.coord == 5
        assert tuji_1.notation == "9G5※"

    def test_skips_marker_cells(self) -> None:
        """`△` `○` `-` `＼` 等のマーカーセルは min_index が無いので skip。"""
        table = PdfTable(
            headers=["施設名", "0歳児"],
            rows=[["藤沢保育園", "△"]],
        )
        entries = parse_min_index_table(table=table, source_pdf_url=_SOURCE, resolver=_resolver())
        assert entries == []

    def test_skips_unresolved_facility(self) -> None:
        """resolver で解決できない施設名は skip。"""
        table = PdfTable(
            headers=["施設名", "0歳児"],
            rows=[
                ["未知保育園", "10F11"],
                ["藤沢保育園", "8F10"],
            ],
        )
        entries = parse_min_index_table(table=table, source_pdf_url=_SOURCE, resolver=_resolver())
        assert len(entries) == 1
        assert entries[0].facility_id == "kouritsu-aaa"

    def test_invalid_format_skipped(self) -> None:
        """`10F` のような不完全フォーマットは skip。"""
        table = PdfTable(
            headers=["施設名", "0歳児", "1歳児"],
            rows=[["藤沢保育園", "10F", "abc"]],
        )
        entries = parse_min_index_table(table=table, source_pdf_url=_SOURCE, resolver=_resolver())
        assert entries == []

    def test_returns_empty_when_no_facility_column(self) -> None:
        table = PdfTable(
            headers=["A", "B"],
            rows=[["x", "10F11"]],
        )
        entries = parse_min_index_table(table=table, source_pdf_url=_SOURCE, resolver=_resolver())
        assert entries == []

    def test_returns_empty_when_no_age_columns(self) -> None:
        table = PdfTable(
            headers=["施設名", "備考"],
            rows=[["藤沢保育園", "10F11"]],
        )
        entries = parse_min_index_table(table=table, source_pdf_url=_SOURCE, resolver=_resolver())
        assert entries == []


class TestMinIndexEntryModel:
    def test_frozen(self) -> None:
        e = MinIndexEntry(
            facility_id="x",
            age_class=0,
            basic=10,
            priority="F",
            coord=11,
            notation="10F11",
            source_pdf_url=_SOURCE,
        )
        try:
            e.basic = 99  # type: ignore[misc]
            raise AssertionError("expected frozen model")
        except Exception:
            pass
