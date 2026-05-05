"""PR 2: line_flex の分析 bubble (summary / networth / anomalies) テスト。

Flex JSON 構造の純関数テスト。実際の LINE 表示は手動確認。
"""

from __future__ import annotations

from decimal import Decimal

from services.line_flex import (
    anomalies_bubble,
    networth_bubble,
    summary_bubble,
)

# ---- summary_bubble ----


def test_summary_bubble_minimal_structure():
    bubble = summary_bubble(
        period_label="2025/10",
        total_income=Decimal(480_000),
        total_expense=Decimal(320_000),
        net=Decimal(160_000),
        savings_rate=Decimal("0.333"),
        fixed=Decimal(200_000),
        variable=Decimal(120_000),
        top_categories=[
            ("housing", Decimal(120_000)),
            ("food", Decimal(80_000)),
        ],
    )
    assert bubble["type"] == "bubble"
    assert "📊 サマリ (2025/10)" in bubble["header"]["contents"][0]["text"]
    body_texts = _flatten_text(bubble["body"])
    assert any("収入" in t for t in body_texts)
    assert any("¥480,000" in t for t in body_texts)
    assert any("ネット" in t for t in body_texts)
    assert any("+¥160,000" in t for t in body_texts)
    assert any("33.3%" in t for t in body_texts)
    assert any("housing" in t for t in body_texts)
    assert any("¥120,000" in t for t in body_texts)


def test_summary_bubble_handles_negative_net():
    bubble = summary_bubble(
        period_label="2025/10",
        total_income=Decimal(300_000),
        total_expense=Decimal(400_000),
        net=Decimal(-100_000),
        savings_rate=Decimal("-0.333"),
        fixed=Decimal(250_000),
        variable=Decimal(150_000),
        top_categories=[],
    )
    body_texts = _flatten_text(bubble["body"])
    # 赤字: -¥100,000 が表示される
    assert any("-¥100,000" in t for t in body_texts)


def test_summary_bubble_no_categories_skips_section():
    bubble = summary_bubble(
        period_label="2025/10",
        total_income=Decimal(0),
        total_expense=Decimal(0),
        net=Decimal(0),
        savings_rate=Decimal(0),
        fixed=Decimal(0),
        variable=Decimal(0),
        top_categories=[],
    )
    body_texts = _flatten_text(bubble["body"])
    assert not any("カテゴリ Top" in t for t in body_texts)


# ---- networth_bubble ----


def test_networth_bubble_basic():
    bubble = networth_bubble(
        as_of_label="2025/10/15",
        total_assets=Decimal(8_500_000),
        total_liabilities=Decimal(2_000_000),
        net_worth=Decimal(6_500_000),
        by_kind_assets={"deposit": Decimal(5_000_000), "stock": Decimal(3_500_000)},
        by_kind_liabilities={"mortgage": Decimal(2_000_000)},
    )
    assert "💰 純資産 (2025/10/15 時点)" in bubble["header"]["contents"][0]["text"]
    body_texts = _flatten_text(bubble["body"])
    assert any("¥8,500,000" in t for t in body_texts)  # 総資産
    assert any("¥2,000,000" in t for t in body_texts)  # 総負債
    assert any("¥6,500,000" in t for t in body_texts)  # 純資産
    assert any("deposit" in t for t in body_texts)
    assert any("mortgage" in t for t in body_texts)


def test_networth_bubble_assets_sorted_desc():
    bubble = networth_bubble(
        as_of_label="2025/10/15",
        total_assets=Decimal(10_000_000),
        total_liabilities=Decimal(0),
        net_worth=Decimal(10_000_000),
        by_kind_assets={
            "deposit": Decimal(2_000_000),
            "stock": Decimal(6_000_000),
            "bond": Decimal(2_000_000),
        },
        by_kind_liabilities={},
    )
    body_texts = _flatten_text(bubble["body"])
    # stock (6M) が deposit (2M) より上に来る
    stock_idx = next(i for i, t in enumerate(body_texts) if "stock" in t)
    deposit_idx = next(i for i, t in enumerate(body_texts) if "deposit" in t)
    assert stock_idx < deposit_idx


def test_networth_bubble_no_liabilities_skips_section():
    bubble = networth_bubble(
        as_of_label="2025/10/15",
        total_assets=Decimal(5_000_000),
        total_liabilities=Decimal(0),
        net_worth=Decimal(5_000_000),
        by_kind_assets={"deposit": Decimal(5_000_000)},
        by_kind_liabilities={},
    )
    body_texts = _flatten_text(bubble["body"])
    assert not any(t == "負債" for t in body_texts)


# ---- anomalies_bubble ----


def test_anomalies_bubble_with_findings():
    bubble = anomalies_bubble(
        target_month_label="2025/10",
        anomalies=[
            ("food", Decimal(180_000), Decimal(80_000), Decimal("4.2")),
            ("communication", Decimal(60_000), Decimal(25_000), Decimal("3.5")),
        ],
        history_months=6,
    )
    assert "⚠️ 異常検知 (2025/10)" in bubble["header"]["contents"][0]["text"]
    body_texts = _flatten_text(bubble["body"])
    assert any("food" in t for t in body_texts)
    assert any("¥180,000" in t for t in body_texts)
    assert any("z=4.2σ" in t for t in body_texts)
    assert any("communication" in t for t in body_texts)


def test_anomalies_bubble_empty_shows_no_anomaly_message():
    bubble = anomalies_bubble(
        target_month_label="2025/10",
        anomalies=[],
        history_months=6,
    )
    body_texts = _flatten_text(bubble["body"])
    assert any("3σ" in t and "ありません" in t for t in body_texts)


def test_anomalies_bubble_truncates_long_list():
    """5 件超でも 5 件までしか表示されない (top categories cap)。"""
    long_list = [
        (f"cat_{i}", Decimal(100_000 - i), Decimal(50_000), Decimal("4.0"))
        for i in range(10)
    ]
    bubble = anomalies_bubble(
        target_month_label="2025/10",
        anomalies=long_list,
        history_months=6,
    )
    body_texts = _flatten_text(bubble["body"])
    # cat_0..4 は出る、cat_5 以降は出ない
    assert any("cat_0" in t for t in body_texts)
    assert any("cat_4" in t for t in body_texts)
    assert not any("cat_5" in t for t in body_texts)


# ---- helpers ----


def _flatten_text(node: dict | list) -> list[str]:
    """Flex JSON を再帰的に走査して全 text 値を集める。"""
    out: list[str] = []
    if isinstance(node, list):
        for item in node:
            out.extend(_flatten_text(item))
        return out
    if isinstance(node, dict):
        if node.get("type") == "text" and isinstance(node.get("text"), str):
            out.append(node["text"])
        for v in node.values():
            if isinstance(v, (dict, list)):
                out.extend(_flatten_text(v))
    return out
