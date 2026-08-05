"""OCR 項目抽出（extract_fields）と Mock エンジンの単体テスト。"""

from __future__ import annotations

from app.services.ocr import MockOcrEngine, build_ocr_engine, extract_fields


class TestExtractFields:
    def test_extracts_zip_address_name_from_envelope(self) -> None:
        text = "〒100-0001\n東京都千代田区千代田1-1\n山田太郎 様"
        draft = extract_fields(text)
        assert draft.zip == "100-0001"
        assert "千代田区" in draft.address
        assert draft.name == "山田太郎"

    def test_zip_without_hyphen_is_normalized(self) -> None:
        draft = extract_fields("1000001\n東京都千代田区")
        assert draft.zip == "100-0001"

    def test_honorific_is_stripped_from_name(self) -> None:
        draft = extract_fields("大阪府大阪市北区\n鈴木花子さん")
        assert draft.name == "鈴木花子"

    def test_company_line_is_not_taken_as_name(self) -> None:
        text = "株式会社サンプル\n東京都渋谷区1-2-3\n佐藤一郎"
        draft = extract_fields(text)
        assert draft.name == "佐藤一郎"

    def test_line_with_digits_is_skipped_for_name(self) -> None:
        text = "090-1234-5678\n愛知県名古屋市中区\n田中三郎"
        draft = extract_fields(text)
        assert draft.name == "田中三郎"

    def test_empty_text_yields_empty_draft(self) -> None:
        draft = extract_fields("")
        assert draft.name == "" and draft.address == "" and draft.zip == ""

    def test_no_address_hint_leaves_address_blank(self) -> None:
        draft = extract_fields("ただのメモ書き")
        assert draft.address == ""


class TestEngineFactory:
    def test_mock_is_default(self) -> None:
        engine = build_ocr_engine("mock")
        assert isinstance(engine, MockOcrEngine)

    def test_mock_returns_configured_text(self) -> None:
        engine = MockOcrEngine("〒100-0001\n東京都\n山田")
        assert "東京都" in engine.recognize(b"ignored")
