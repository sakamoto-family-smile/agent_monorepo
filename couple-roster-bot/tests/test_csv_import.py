"""CSV 一括インポートの単体テスト。"""

from __future__ import annotations

from app.models import dedup_key
from app.services.csv_import import decode_csv_bytes, prepare_import


def _csv(text: str, encoding: str = "utf-8") -> bytes:
    return text.encode(encoding)


class TestDecode:
    def test_decodes_utf8(self) -> None:
        assert decode_csv_bytes("名前".encode()) == "名前"

    def test_decodes_shift_jis(self) -> None:
        assert decode_csv_bytes("住所".encode("cp932")) == "住所"

    def test_decodes_utf8_with_bom(self) -> None:
        assert decode_csv_bytes("﻿名前".encode()) == "名前"


class TestPrepareImport:
    def test_valid_rows_become_drafts(self) -> None:
        data = _csv(
            "name,address,relation\n"
            "山田太郎,東京都港区,父\n"
            "鈴木花子,大阪市北区,友人・知人\n"
        )
        preview = prepare_import(data, existing_keys=set())
        assert preview.valid_count == 2
        assert preview.error_count == 0
        assert preview.total_rows == 2
        assert preview.valid_drafts[0].name == "山田太郎"

    def test_japanese_headers_are_mapped(self) -> None:
        data = _csv("名前,住所,間柄\n田中一郎,名古屋市,親戚\n")
        preview = prepare_import(data, existing_keys=set())
        assert preview.valid_count == 1
        assert preview.valid_drafts[0].relation == "親戚"

    def test_columns_can_be_unordered(self) -> None:
        data = _csv("relation,name,note,address\n母,佐藤,元気,札幌市\n")
        preview = prepare_import(data, existing_keys=set())
        assert preview.valid_count == 1
        draft = preview.valid_drafts[0]
        assert draft.name == "佐藤" and draft.address == "札幌市"

    def test_invalid_relation_is_reported_as_error(self) -> None:
        data = _csv("name,address,relation\n山田,東京,ペット\n")
        preview = prepare_import(data, existing_keys=set())
        assert preview.valid_count == 0
        assert preview.error_count == 1
        assert preview.errors[0].line == 2
        assert "間柄" in preview.errors[0].reason

    def test_missing_required_field_is_error(self) -> None:
        data = _csv("name,address,relation\n,東京,父\n")
        preview = prepare_import(data, existing_keys=set())
        assert preview.error_count == 1
        assert "名前" in preview.errors[0].reason

    def test_duplicate_within_batch_is_skipped(self) -> None:
        data = _csv(
            "name,address,relation\n"
            "山田太郎,東京都港区,父\n"
            "山田 太郎,東京都 港区,父\n"  # 空白違いの重複
        )
        preview = prepare_import(data, existing_keys=set())
        assert preview.valid_count == 1
        assert preview.duplicate_count == 1

    def test_duplicate_against_existing_is_skipped(self) -> None:
        existing = {dedup_key("山田太郎", "東京都港区")}
        data = _csv("name,address,relation\n山田太郎,東京都港区,父\n")
        preview = prepare_import(data, existing_keys=existing)
        assert preview.valid_count == 0
        assert preview.duplicate_count == 1

    def test_blank_lines_are_ignored(self) -> None:
        data = _csv("name,address,relation\n山田,東京,父\n,,\n")
        preview = prepare_import(data, existing_keys=set())
        assert preview.total_rows == 1
        assert preview.valid_count == 1

    def test_missing_required_header_returns_single_error(self) -> None:
        data = _csv("foo,bar\n1,2\n")
        preview = prepare_import(data, existing_keys=set())
        assert preview.valid_count == 0
        assert preview.errors[0].line == 1
        assert "名前" in preview.errors[0].reason

    def test_summary_string(self) -> None:
        data = _csv("name,address,relation\n山田,東京,父\n鈴木,大阪,ペット\n")
        preview = prepare_import(data, existing_keys=set())
        summary = preview.summary()
        assert "登録可" in summary and "エラー" in summary
