from datetime import date
from decimal import Decimal

import pytest

from agents.csv_importer import parse_bytes, parse_file
from models.transaction import TransactionKind
from tests.fixtures.build_sample_csv import build_csv


class TestParseBytes:
    def test_default_sample_imports_income_and_expense_only(self):
        result = parse_bytes(build_csv())

        assert result.total_rows == 5
        # 振替 + 計算対象外 を除外し 3 件
        assert result.imported == 3
        assert result.skipped_transfer == 1
        assert result.skipped_excluded == 1
        assert result.skipped_invalid == 0

    def test_encoding_detected_as_cp932(self):
        result = parse_bytes(build_csv(encoding="cp932"))
        assert result.encoding in ("cp932", "shift_jis")

    def test_utf8_encoded_csv_also_parsed(self):
        result = parse_bytes(build_csv(encoding="utf-8"))
        assert result.encoding in ("utf-8-sig", "utf-8")
        assert result.imported == 3

    def test_transaction_fields_populated(self):
        result = parse_bytes(build_csv())
        tx = next(t for t in result.transactions if t.source_id == "sample-001")

        assert tx.date == date(2026, 4, 1)
        assert tx.content == "スーパー購入"
        assert tx.amount == Decimal("-3500")
        assert tx.account == "テスト銀行"
        assert tx.category == "食費"
        assert tx.subcategory == "食料品"
        assert tx.is_transfer is False
        assert tx.is_target is True
        assert tx.kind == TransactionKind.EXPENSE
        assert tx.absolute_amount == Decimal("3500")

    def test_income_row_has_income_kind(self):
        result = parse_bytes(build_csv())
        tx = next(t for t in result.transactions if t.source_id == "sample-003")
        assert tx.kind == TransactionKind.INCOME
        assert tx.amount == Decimal("300000")

    def test_include_transfers_keeps_them(self):
        result = parse_bytes(build_csv(), include_transfers=True)
        assert result.imported == 4
        assert result.skipped_transfer == 0
        transfer_tx = next(t for t in result.transactions if t.source_id == "sample-004")
        assert transfer_tx.is_transfer
        assert transfer_tx.kind == TransactionKind.TRANSFER

    def test_include_excluded_keeps_them(self):
        result = parse_bytes(build_csv(), include_excluded=True)
        assert result.imported == 4
        assert result.skipped_excluded == 0

    def test_totals_computed_correctly(self):
        result = parse_bytes(build_csv())
        assert result.income_total == Decimal("300000")
        assert result.expense_total == Decimal("4700")  # 3500 + 1200
        assert result.net == Decimal("295300")

    def test_duplicates_deduplicated(self):
        dup = {
            "計算対象": "1", "日付": "2026/04/01", "内容": "重複",
            "金額（円）": "-1000", "保有金融機関": "テスト銀行",
            "大項目": "食費", "中項目": "食料品", "メモ": "", "振替": "0",
            "ID": "dup-id",
        }
        raw = build_csv(rows=[dup, dup, dup])
        result = parse_bytes(raw)
        assert result.imported == 1
        assert result.duplicates_in_file == 2

    def test_invalid_row_is_skipped_not_raised(self):
        bad = {
            "計算対象": "1", "日付": "NOT_A_DATE", "内容": "不正",
            "金額（円）": "-1000", "保有金融機関": "X",
            "大項目": "A", "中項目": "B", "メモ": "", "振替": "0",
            "ID": "bad-1",
        }
        good = {
            "計算対象": "1", "日付": "2026/04/02", "内容": "正常",
            "金額（円）": "-500", "保有金融機関": "X",
            "大項目": "A", "中項目": "B", "メモ": "", "振替": "0",
            "ID": "good-1",
        }
        result = parse_bytes(build_csv(rows=[bad, good]))
        assert result.skipped_invalid == 1
        assert result.imported == 1

    def test_missing_column_raises_header_error(self):
        # 'ID' 列を落とした不正ヘッダ
        raw = (
            '"計算対象","日付","内容","金額（円）","保有金融機関","大項目","中項目","メモ","振替"\n'
            '"1","2026/04/01","x","-100","y","z","a","","0"\n'
        ).encode("cp932")
        with pytest.raises(ValueError, match="header mismatch"):
            parse_bytes(raw)

    def test_empty_memo_becomes_none(self):
        result = parse_bytes(build_csv())
        tx = next(t for t in result.transactions if t.source_id == "sample-001")
        assert tx.memo is None

    def test_non_empty_memo_preserved(self):
        result = parse_bytes(build_csv())
        tx = next(t for t in result.transactions if t.source_id == "sample-002")
        assert tx.memo == "技術書"


class TestParseFile:
    def test_parse_file_roundtrip(self, tmp_path):
        csv_path = tmp_path / "sample.csv"
        csv_path.write_bytes(build_csv())

        result = parse_file(csv_path)
        assert result.source_file == str(csv_path)
        assert result.imported == 3
