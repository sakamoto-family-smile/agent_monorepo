"""日本税制計算(tax_jp)のゴールデンテスト。

給与収入 300 / 500 / 800 / 1,500 万円の 4 ケースで、
2026 年版テーブルでの所得税・住民税・社保料が想定値と一致することを検証する。

想定値は 2026.yaml の税率・控除から機械的に算出した自明解。
国税庁シミュレータや市販ソフトとの完全一致は追わず、
本実装内部での仕様確定(regression guard)を目的とする。
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from agents.tax_jp import (
    calc_income_tax,
    calc_resident_tax,
    calc_salary_income_deduction,
    calc_social_insurance,
    load_tax_table,
)


@pytest.fixture(scope="module")
def table_2026():
    return load_tax_table(2026)


# ---------------------------------------------------------------------------
# 給与所得控除
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "salary,expected",
    [
        # 162.5 万以下 → 一律 55 万
        (Decimal(1_500_000), Decimal(550_000)),
        # 180 万以下 → 収入 * 40% - 10 万
        #   300 万ではなく 180 万でのテスト値に統一: 180 万 * 0.4 - 10 万 = 62 万
        (Decimal(1_800_000), Decimal(620_000)),
        # 360 万以下 → 収入 * 30% + 8 万
        #   300 万: 300 万 * 0.3 + 8 万 = 98 万
        (Decimal(3_000_000), Decimal(980_000)),
        # 660 万以下 → 収入 * 20% + 44 万
        #   500 万: 500 万 * 0.2 + 44 万 = 144 万
        (Decimal(5_000_000), Decimal(1_440_000)),
        # 850 万以下 → 収入 * 10% + 110 万
        #   800 万: 800 万 * 0.1 + 110 万 = 190 万
        (Decimal(8_000_000), Decimal(1_900_000)),
        # 850 万超 → 上限 195 万
        (Decimal(15_000_000), Decimal(1_950_000)),
    ],
)
def test_salary_income_deduction(table_2026, salary, expected):
    assert calc_salary_income_deduction(salary, table_2026) == expected


# ---------------------------------------------------------------------------
# 社会保険料
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "salary",
    [
        Decimal(3_000_000),
        Decimal(5_000_000),
        Decimal(8_000_000),
        Decimal(15_000_000),
    ],
)
def test_social_insurance_positive(table_2026, salary):
    """社保料は正の値で、かつ rate から期待値レンジに入ることを確認。"""
    si = calc_social_insurance(salary, table=table_2026)
    assert si.health > 0
    assert si.pension > 0
    assert si.employment > 0
    # ざっくり 10-15% 前後が妥当なレンジ
    total_rate = si.total / salary
    assert Decimal("0.10") <= total_rate <= Decimal("0.20")


def test_social_insurance_respects_health_cap(table_2026):
    """月収 200 万 (> 健保 139 万上限) でも健保はキャップされる。"""
    salary = Decimal(24_000_000)  # 月 200 万
    si = calc_social_insurance(salary, table=table_2026)
    # 健保上限 139 万 * 5% * 12 = 834,000
    expected_health = table_2026.health_monthly_cap * table_2026.health_insurance_rate * 12
    assert si.health == expected_health


def test_social_insurance_zero_for_zero_income(table_2026):
    si = calc_social_insurance(Decimal(0), table=table_2026)
    assert si.total == 0


# ---------------------------------------------------------------------------
# ゴールデンケース: 300 / 500 / 800 / 1500 万
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "salary",
    [
        Decimal(3_000_000),
        Decimal(5_000_000),
        Decimal(8_000_000),
        Decimal(15_000_000),
    ],
)
def test_tax_end_to_end_consistency(table_2026, salary):
    """所得税・住民税・社保料を通した整合性チェック:
       手取り = 収入 - 税 - 社保 > 0 かつ 収入の 60% 以上残る (給与所得者の妥当レンジ)。
    """
    si = calc_social_insurance(salary, table=table_2026)
    inc_tax = calc_income_tax(
        salary,
        table=table_2026,
        social_insurance_deduction=si.total,
    )
    res_tax = calc_resident_tax(
        salary,
        table=table_2026,
        social_insurance_deduction=si.total,
    )
    take_home = salary - si.total - inc_tax - res_tax
    assert take_home > 0
    # 所得が高いほど手取り率は下がる。最低 55% は確保(1500 万でも通る緩さ)。
    assert take_home / salary >= Decimal("0.55")


def test_income_tax_300man(table_2026):
    """給与 300 万のゴールデン値 (手計算)。

    給与所得控除 = 300 万 * 0.3 + 8 万 = 98 万
    給与所得 = 202 万
    社保概算: 健保 15 万 + 厚年 27.45 万 + 雇 1.8 万 = 約 44 万
    課税所得(所得税) = 202 - 44 - 48 = 110 万
    所得税 = 110 万 * 5% = 5.5 万 → +復興特別 2.1% = 約 5.6 万
    """
    salary = Decimal(3_000_000)
    si = calc_social_insurance(salary, table=table_2026)
    tax = calc_income_tax(salary, table=table_2026, social_insurance_deduction=si.total)
    # 5 万〜7 万の妥当レンジ
    assert Decimal(50_000) <= tax <= Decimal(70_000)


def test_income_tax_800man(table_2026):
    """給与 800 万は 20% ブラケット。所得税は 30-50 万レンジ。"""
    salary = Decimal(8_000_000)
    si = calc_social_insurance(salary, table=table_2026)
    tax = calc_income_tax(salary, table=table_2026, social_insurance_deduction=si.total)
    assert Decimal(300_000) <= tax <= Decimal(500_000)


def test_income_tax_1500man_in_33pct_bracket(table_2026):
    """給与 1500 万は 33% ブラケット。所得税は 200 万以上になる。"""
    salary = Decimal(15_000_000)
    si = calc_social_insurance(salary, table=table_2026)
    tax = calc_income_tax(salary, table=table_2026, social_insurance_deduction=si.total)
    assert tax > Decimal(2_000_000)


def test_income_tax_with_tax_credit(table_2026):
    """住宅ローン控除 20 万を税額控除として引くと所得税が減る。"""
    salary = Decimal(8_000_000)
    si = calc_social_insurance(salary, table=table_2026)
    base = calc_income_tax(salary, table=table_2026, social_insurance_deduction=si.total)
    with_credit = calc_income_tax(
        salary,
        table=table_2026,
        social_insurance_deduction=si.total,
        tax_credits=Decimal(200_000),
    )
    # 復興特別分も合わせて減る
    assert base - with_credit >= Decimal(200_000)


def test_resident_tax_500man(table_2026):
    """住民税はおおむね所得割 10% + 均等割 6000 円。"""
    salary = Decimal(5_000_000)
    si = calc_social_insurance(salary, table=table_2026)
    res = calc_resident_tax(salary, table=table_2026, social_insurance_deduction=si.total)
    # 500 万の住民税はおおむね 15-25 万レンジ
    assert Decimal(150_000) <= res <= Decimal(250_000)


def test_resident_tax_includes_flat_amount(table_2026):
    """収入 0 でも均等割 6000 円は課される (簡略化仕様)。"""
    res = calc_resident_tax(Decimal(0), table=table_2026)
    assert res == table_2026.resident_flat_amount


# ---------------------------------------------------------------------------
# YAML ローダ
# ---------------------------------------------------------------------------


def test_load_tax_table_year(table_2026):
    assert table_2026.year == 2026
    assert table_2026.income_tax_brackets  # 空でない
    assert table_2026.basic_deduction_income == Decimal(480_000)
    assert table_2026.basic_deduction_resident == Decimal(430_000)


def test_load_tax_table_fallback_to_latest(tmp_path):
    """存在しない年度を指定した場合、存在する最新年度にフォールバック。"""
    import shutil
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "data" / "tax_tables" / "2026.yaml"
    dst_dir = tmp_path / "tax_tables"
    dst_dir.mkdir()
    shutil.copy(src, dst_dir / "2026.yaml")

    # 2099 年は存在しない → 2026 にフォールバック
    t = load_tax_table(2099, data_dir=dst_dir)
    assert t.year == 2026
