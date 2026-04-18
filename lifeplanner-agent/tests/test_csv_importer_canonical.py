"""csv_importer が canonical / expense_type を付与することを検証。"""

from __future__ import annotations

from agents.csv_importer import parse_bytes
from tests.fixtures.build_sample_csv import build_csv


def test_imported_transactions_have_canonical_categories():
    """サンプル CSV をパースすると各 transaction に canonical_category が付く。"""
    raw = build_csv()
    result = parse_bytes(raw)

    by_source = {t.source_id: t for t in result.transactions}
    # 食費 → canonical=food, variable
    assert by_source["sample-001"].canonical_category == "food"
    assert by_source["sample-001"].expense_type == "variable"
    # 教養・教育 → education, variable
    assert by_source["sample-002"].canonical_category == "education"
    assert by_source["sample-002"].expense_type == "variable"


def test_unknown_category_falls_back_to_other():
    """YAML にない大項目は other / variable にフォールバック。"""
    rows = [
        {
            "計算対象": "1", "日付": "2026/04/01", "内容": "unknown",
            "金額（円）": "-100", "保有金融機関": "X",
            "大項目": "未知の項目XYZ", "中項目": "", "メモ": "", "振替": "0",
            "ID": "row-unknown",
        }
    ]
    raw = build_csv(rows)
    result = parse_bytes(raw)
    tx = result.transactions[0]
    assert tx.canonical_category == "other"
    assert tx.expense_type == "variable"


def test_fixed_cost_category_is_labeled_fixed():
    """住宅は fixed として付与される。"""
    rows = [
        {
            "計算対象": "1", "日付": "2026/04/01", "内容": "家賃",
            "金額（円）": "-100000", "保有金融機関": "X",
            "大項目": "住宅", "中項目": "家賃", "メモ": "", "振替": "0",
            "ID": "row-housing",
        }
    ]
    raw = build_csv(rows)
    result = parse_bytes(raw)
    tx = result.transactions[0]
    assert tx.canonical_category == "housing"
    assert tx.expense_type == "fixed"


def test_income_category_is_labeled_income():
    """給与は income として付与される。"""
    rows = [
        {
            "計算対象": "1", "日付": "2026/04/25", "内容": "月給",
            "金額（円）": "400000", "保有金融機関": "X",
            "大項目": "給与", "中項目": "", "メモ": "", "振替": "0",
            "ID": "row-salary",
        }
    ]
    raw = build_csv(rows)
    result = parse_bytes(raw)
    tx = result.transactions[0]
    assert tx.canonical_category == "salary"
    assert tx.expense_type == "income"
