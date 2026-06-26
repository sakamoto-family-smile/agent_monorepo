"""型別接地・正規化のテスト。"""

from __future__ import annotations

from attachment_pipeline.schema import FieldType
from attachment_pipeline.validate.grounding import (
    ground,
    ground_numeric,
    normalize_amount,
    normalize_date,
)


def test_normalize_amount_strips_currency_and_commas():
    assert normalize_amount("18,800") == 18800
    assert normalize_amount("¥1,200円") == 1200
    assert normalize_amount("１８，８００") == 18800  # 全角
    assert normalize_amount("abc") is None


def test_normalize_date_handles_jp_and_iso_and_rejects_impossible():
    assert normalize_date("2024年1月5日") == "2024-01-05"
    assert normalize_date("2024-01-05") == "2024-01-05"
    assert normalize_date("2024/1/5") == "2024-01-05"
    assert normalize_date("2024年2月30日") is None  # 実在しない日付


def test_substring_trap_is_rejected():
    # 「18,800」しか無い原文で「800」を接地しようとしても、語境界トークン化により
    # 18,800 の内部一致は起きず、800 という独立トークンも無いので接地失敗。
    text = "合計: 18,800 円"
    g = ground_numeric("800", text, evidence_span="合計: 18,800 円")
    assert g.found is False


def test_normalized_value_still_grounds():
    # H1: LLM が「18800」(カンマ無し) を返しても原文「18,800」へ接地できる。
    text = "合計: 18,800 円"
    g = ground_numeric("18800", text, evidence_span="合計: 18,800 円")
    assert g.found is True
    assert g.canonical == "18800"


def test_same_value_duplicate_picks_one_not_reject():
    # 同値が2箇所 (単価=金額) でも、どちらを選んでも値は同一なので採用される。
    text = "単価 1,200  金額 1,200"
    g = ground_numeric("1,200", text, evidence_span="単価 1,200")
    assert g.found is True
    assert g.canonical == "1200"


def test_code_exact_match():
    text = "請求書番号: INV-2024-00123"
    g = ground(FieldType.CODE, "INV-2024-00123", text, "請求書番号: INV-2024-00123")
    assert g.found is True
    g2 = ground(FieldType.CODE, "INV-2024-99999", text, "")
    assert g2.found is False


def test_fuzzy_name_grounds_exact():
    text = "発行元:\n  株式会社XYZ製作所\n"
    g = ground(FieldType.NAME, "株式会社XYZ製作所", text, "株式会社XYZ製作所")
    assert g.found is True


def test_hallucinated_name_not_grounded():
    text = "発行元:\n  株式会社XYZ製作所\n"
    g = ground(FieldType.NAME, "株式会社架空ホールディングス", text, "")
    assert g.found is False
