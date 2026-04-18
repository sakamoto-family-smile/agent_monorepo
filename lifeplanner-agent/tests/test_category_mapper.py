"""CategoryMapper / mf_to_canonical.yaml のテスト。"""

from __future__ import annotations

import pytest

from services.category_mapper import load_category_mapper


@pytest.fixture(scope="module")
def mapper():
    return load_category_mapper()


def test_known_fixed_cost_resolves_to_housing(mapper):
    c = mapper.resolve("住宅")
    assert c.canonical == "housing"
    assert c.expense_type == "fixed"


def test_known_variable_cost_resolves_to_food(mapper):
    c = mapper.resolve("食費")
    assert c.canonical == "food"
    assert c.expense_type == "variable"


def test_income_category(mapper):
    c = mapper.resolve("給与")
    assert c.canonical == "salary"
    assert c.expense_type == "income"


def test_unknown_falls_back_to_other_variable(mapper):
    c = mapper.resolve("存在しない大項目")
    assert c.canonical == "other"
    assert c.expense_type == "variable"


def test_none_falls_back(mapper):
    c = mapper.resolve(None)
    assert c.canonical == "other"


def test_whitespace_is_trimmed(mapper):
    c = mapper.resolve("  食費  ")
    assert c.canonical == "food"


def test_fallback_is_immutable(mapper):
    """CategoryMapper は immutable な dataclass で、同じ fallback を返す。"""
    a = mapper.resolve("未知1")
    b = mapper.resolve("未知2")
    assert a is b or a == b
