"""facility_parser のテスト。

`HtmlTable` (テーブル + 行ごとのリンク) を `FacilityRecord` に変換する parser。
認可 / 認可外で列構成が異なるため、片方ずつ専用関数を持つ。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fujisawa_platform.etl._html_table import HtmlTable
from fujisawa_platform.etl.facility_parser import (
    parse_authorized_table,
    parse_unauthorized_table,
    parse_walk_minutes,
    slugify_facility_id,
)

_NOW = datetime(2026, 5, 10, 0, 0, tzinfo=UTC)
_AUTHORIZED_URL = "https://www.city.fujisawa.kanagawa.jp/.../ninka.html"
_UNAUTHORIZED_URL = "https://www.city.fujisawa.kanagawa.jp/.../ninkagai.html"


# ─────────────────────────────────────────────────────────────────────
# slugify_facility_id
# ─────────────────────────────────────────────────────────────────────


class TestSlugifyFacilityId:
    def test_uses_facility_type_prefix_and_sha256_short(self) -> None:
        a = slugify_facility_id("公立保育所", "藤沢保育園")
        assert a.startswith("kouritsu-")
        # 末尾は SHA-256 の先頭 12 桁
        assert len(a.split("-", 1)[1]) == 12

    def test_same_input_same_id(self) -> None:
        assert slugify_facility_id("公立保育所", "藤沢保育園") == slugify_facility_id(
            "公立保育所", "藤沢保育園"
        )

    def test_different_input_different_id(self) -> None:
        a = slugify_facility_id("公立保育所", "藤沢保育園")
        b = slugify_facility_id("公立保育所", "辻堂保育園")
        assert a != b


# ─────────────────────────────────────────────────────────────────────
# parse_walk_minutes (アクセス情報パース)
# ─────────────────────────────────────────────────────────────────────


class TestParseWalkMinutes:
    @pytest.mark.parametrize(
        ("text", "expected_station", "expected_minutes"),
        [
            ("藤沢駅北口徒歩 7 分", "藤沢駅", 7),
            ("藤沢駅徒歩7分", "藤沢駅", 7),
            ("辻堂駅 徒歩 10 分", "辻堂駅", 10),
            ("湘南台駅から徒歩15分", "湘南台駅", 15),
        ],
    )
    def test_extracts_station_and_minutes(
        self, text: str, expected_station: str, expected_minutes: int
    ) -> None:
        station, minutes = parse_walk_minutes(text)
        assert station == expected_station
        assert minutes == expected_minutes

    def test_no_match_returns_none_pair(self) -> None:
        station, minutes = parse_walk_minutes("藤沢市朝日町 1-1")
        assert station is None
        assert minutes is None


# ─────────────────────────────────────────────────────────────────────
# parse_authorized_table
# ─────────────────────────────────────────────────────────────────────


def _authorized_table() -> HtmlTable:
    return HtmlTable(
        headers=["施設名", "所在地番", "電話番号", "外部リンク"],
        rows=[
            ["藤沢保育園", "藤沢市朝日町 1-1", "0466-12-3456", "公式 HP"],
            ["辻堂第二保育園(分園)", "藤沢市辻堂 2-2", "0466-22-3456", ""],
        ],
        row_links=[
            {3: "https://example.com/fuji"},
            {},
        ],
    )


class TestParseAuthorizedTable:
    def test_returns_one_record_per_row(self) -> None:
        records = parse_authorized_table(
            table=_authorized_table(),
            facility_type="公立保育所",
            source_url=_AUTHORIZED_URL,
            as_of=_NOW,
        )
        assert len(records) == 2

    def test_basic_fields(self) -> None:
        records = parse_authorized_table(
            table=_authorized_table(),
            facility_type="公立保育所",
            source_url=_AUTHORIZED_URL,
            as_of=_NOW,
        )
        a = records[0]
        assert a.name == "藤沢保育園"
        assert a.facility_type == "公立保育所"
        assert a.address == "藤沢市朝日町 1-1"
        assert a.phone == "0466-12-3456"
        assert a.official_url == "https://example.com/fuji"
        assert a.source_url == _AUTHORIZED_URL
        assert a.as_of == _NOW

    def test_official_url_is_none_when_no_link(self) -> None:
        records = parse_authorized_table(
            table=_authorized_table(),
            facility_type="公立保育所",
            source_url=_AUTHORIZED_URL,
            as_of=_NOW,
        )
        b = records[1]
        assert b.official_url is None

    def test_skips_empty_rows(self) -> None:
        table = HtmlTable(
            headers=["施設名", "所在地番", "電話番号"],
            rows=[
                ["", "", ""],
                ["藤沢保育園", "朝日町 1-1", "0466-12-3456"],
            ],
            row_links=[{}, {}],
        )
        records = parse_authorized_table(
            table=table, facility_type="公立保育所", source_url=_AUTHORIZED_URL, as_of=_NOW
        )
        assert len(records) == 1
        assert records[0].name == "藤沢保育園"

    def test_minimum_columns_required(self) -> None:
        """3 列未満の行は skip (列ずれ防止)。"""
        table = HtmlTable(
            headers=["施設名", "所在地番"],
            rows=[["藤沢保育園", "朝日町 1-1"]],
            row_links=[{}],
        )
        records = parse_authorized_table(
            table=table, facility_type="公立保育所", source_url=_AUTHORIZED_URL, as_of=_NOW
        )
        assert records == []


# ─────────────────────────────────────────────────────────────────────
# parse_unauthorized_table (認可外: 駅エリア + 類型抽出 + 徒歩分数)
# ─────────────────────────────────────────────────────────────────────


def _unauthorized_table() -> HtmlTable:
    return HtmlTable(
        headers=["施設名 (類型)", "所在地", "電話番号", "定員"],
        rows=[
            ["A 保育園 (藤沢型 A 型)", "藤沢駅北口徒歩 7 分", "0466-99-0001", "30"],
            ["B 保育室 (企業主導型)", "藤沢市辻堂 3-3", "0466-99-0002", "20"],
        ],
        row_links=[{}, {}],
    )


class TestParseUnauthorizedTable:
    def test_extracts_facility_type_from_name_paren(self) -> None:
        records = parse_unauthorized_table(
            table=_unauthorized_table(),
            source_url=_UNAUTHORIZED_URL,
            as_of=_NOW,
        )
        assert len(records) == 2
        assert records[0].name == "A 保育園"  # 括弧内は名前から外す
        assert records[0].facility_type == "藤沢型 A 型"
        assert records[1].name == "B 保育室"
        assert records[1].facility_type == "企業主導型"

    def test_extracts_walk_minutes_when_present(self) -> None:
        records = parse_unauthorized_table(
            table=_unauthorized_table(),
            source_url=_UNAUTHORIZED_URL,
            as_of=_NOW,
        )
        assert records[0].nearest_station == "藤沢駅"
        assert records[0].walk_minutes == 7
        # 徒歩分数が無いケースは None
        assert records[1].nearest_station is None
        assert records[1].walk_minutes is None

    def test_capacity_parsed_as_int(self) -> None:
        records = parse_unauthorized_table(
            table=_unauthorized_table(),
            source_url=_UNAUTHORIZED_URL,
            as_of=_NOW,
        )
        assert records[0].capacity == 30
        assert records[1].capacity == 20

    def test_facility_type_falls_back_to_unauthorized_when_no_paren(self) -> None:
        table = HtmlTable(
            headers=["施設名", "所在地", "電話番号", "定員"],
            rows=[["C 保育室", "藤沢市湘南台 1-1", "0466-99-0003", "15"]],
            row_links=[{}],
        )
        records = parse_unauthorized_table(table=table, source_url=_UNAUTHORIZED_URL, as_of=_NOW)
        assert records[0].facility_type == "認可外保育施設"
