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
    parse_min_index_tables,
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
            ResolverEntry(facility_id="r4-nijiiro-fuji", canonical_name="にじいろ保育園藤沢"),
            ResolverEntry(facility_id="r4-doremi", canonical_name="どれみちゃいるど保育室"),
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


    def test_fullwidth_age_headers_resolved(self) -> None:
        """Docling は `０歳` (全角) でヘッダーを返すため正規表現を broader 化する。"""
        table = PdfTable(
            headers=["施設名", "０歳", "１歳", "２歳"],
            rows=[["藤沢保育園", "10F11", "○", "8E9"]],
        )
        entries = parse_min_index_table(table=table, source_pdf_url=_SOURCE, resolver=_resolver())
        ages = {e.age_class for e in entries}
        assert ages == {0, 2}

    def test_half_width_age_without_児_suffix(self) -> None:
        """Docling は `0歳` (歳児 ではなく 歳) でも返すため両対応する。"""
        table = PdfTable(
            headers=["施設名", "0歳", "1歳"],
            rows=[["藤沢保育園", "10F11", "○"]],
        )
        entries = parse_min_index_table(table=table, source_pdf_url=_SOURCE, resolver=_resolver())
        assert [e.age_class for e in entries] == [0]


# ─────────────────────────────────────────────────────────────────────
# parse_min_index_tables (複数 table を context-aware に処理)
# ─────────────────────────────────────────────────────────────────────


class TestParseMinIndexTables:
    def test_facility_column_inferred_when_no_explicit_header(self) -> None:
        """実 Docling 出力では `施設名` ヘッダーが無く `公立` などのカテゴリが入る。
        age 列より左の最も左 col (= col 0) を facility 列とみなす。"""
        table = PdfTable(
            headers=["公立", "０歳", "１歳", "２歳"],
            rows=[["藤沢保育園", "10F11", "9F10", "○"]],
        )
        entries = parse_min_index_tables(
            tables=[table], source_pdf_url=_SOURCE, resolver=_resolver()
        )
        assert {e.age_class for e in entries} == {0, 1}
        assert {e.facility_id for e in entries} == {"kouritsu-aaa"}

    def test_docling_header_miss_inherits_prev_columns(self) -> None:
        """Docling が改ページで header を取りこぼし、データ行を headers として誤抽出した
        ケースを、前 table の column 設計を継承して救済する。"""
        ok = PdfTable(
            headers=["公立", "０歳", "１歳", "２歳"],
            rows=[["藤沢保育園", "10F11", "9F10", "○"]],
        )
        # 後続 table は本来 headers であるべき行を data に押し込んでしまっている
        broken = PdfTable(
            headers=["にじいろ保育園藤沢", "10F11※", "10F11※", "10D13"],
            rows=[["辻堂保育園", "8F12", "9F11", "○"]],
        )
        entries = parse_min_index_tables(
            tables=[ok, broken], source_pdf_url=_SOURCE, resolver=_resolver()
        )
        # ok から: 藤沢の (0, 1) = 2 件
        # broken から: にじいろ藤沢の (0, 1, 2) = 3 件, 辻堂の (0, 1) = 2 件
        facility_age = {(e.facility_id, e.age_class) for e in entries}
        assert ("kouritsu-aaa", 0) in facility_age
        assert ("kouritsu-aaa", 1) in facility_age
        assert ("r4-nijiiro-fuji", 0) in facility_age
        assert ("r4-nijiiro-fuji", 1) in facility_age
        assert ("r4-nijiiro-fuji", 2) in facility_age
        assert ("kouritsu-bbb", 0) in facility_age
        assert ("kouritsu-bbb", 1) in facility_age

    def test_header_miss_without_prior_context_skipped(self) -> None:
        """最初の table から age 列が出ない場合は救済できないので skip。"""
        broken = PdfTable(
            headers=["にじいろ保育園藤沢", "10F11"],
            rows=[["辻堂保育園", "8F12"]],
        )
        entries = parse_min_index_tables(
            tables=[broken], source_pdf_url=_SOURCE, resolver=_resolver()
        )
        assert entries == []

    def test_range_age_header_skipped(self) -> None:
        """家庭的保育の `0歳～2歳` 型 range header は本 parser では未対応 → skip。"""
        table = PdfTable(
            headers=["家庭的保育事業", "0歳～2歳"],
            rows=[["藤沢保育園", "10F11"]],
        )
        entries = parse_min_index_tables(
            tables=[table], source_pdf_url=_SOURCE, resolver=_resolver()
        )
        assert entries == []

    def test_small_scale_4col_table(self) -> None:
        """`小規模保育事業` のような 0-2 歳のみ 4 列 table も処理できる。"""
        table = PdfTable(
            headers=["小規模保育事業", "０歳", "１歳", "２歳"],
            rows=[["どれみちゃいるど保育室", "○", "9F13", "-"]],
        )
        entries = parse_min_index_tables(
            tables=[table], source_pdf_url=_SOURCE, resolver=_resolver()
        )
        assert len(entries) == 1
        e = entries[0]
        assert e.facility_id == "r4-doremi"
        assert e.age_class == 1
        assert e.notation == "9F13"


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
