"""バッチ生成計画のテスト。"""

from __future__ import annotations

import pytest

from app.agent import GenerationRequest
from app.batch.plan import (
    DEFAULT_CATEGORIES,
    DEFAULT_GOALS,
    build_round_robin_plan,
    build_targeted_plan,
)


def test_round_robin_plan_total_zero_returns_empty() -> None:
    assert build_round_robin_plan(total=0) == []


def test_round_robin_plan_returns_total_items() -> None:
    plan = build_round_robin_plan(total=10)
    assert len(plan) == 10
    for r in plan:
        assert r.category in DEFAULT_CATEGORIES
        assert r.goal in DEFAULT_GOALS
        assert r.difficulty == "standard"


def test_round_robin_cycles_through_combinations() -> None:
    """組合せを循環的に回す（同じ組合せに偏らない）。"""
    plan = build_round_robin_plan(
        total=8,
        categories=("rules", "signs"),
        goals=("provisional", "full"),
    )
    # 4 組合せが 2 周
    pairs = [(r.category, r.goal) for r in plan]
    unique = set(pairs)
    assert len(unique) == 4


def test_round_robin_difficulty_passed_through() -> None:
    plan = build_round_robin_plan(total=2, difficulty="advanced")
    for r in plan:
        assert r.difficulty == "advanced"


def test_round_robin_rejects_empty_inputs() -> None:
    with pytest.raises(ValueError):
        build_round_robin_plan(total=5, categories=())
    with pytest.raises(ValueError):
        build_round_robin_plan(total=5, goals=())


def test_targeted_plan_repeats_each_request() -> None:
    base = [
        GenerationRequest(goal="full", category="rules", difficulty="standard"),
        GenerationRequest(goal="provisional", category="signs", difficulty="basic"),
    ]
    plan = build_targeted_plan(requests=base, repeat=3)
    assert len(plan) == 6
    # 各 request が 3 回ずつ含まれる
    cats = [r.category for r in plan]
    assert cats.count("rules") == 3
    assert cats.count("signs") == 3


def test_targeted_plan_repeat_zero_returns_empty() -> None:
    base = [GenerationRequest(goal="full", category="rules", difficulty="basic")]
    assert build_targeted_plan(requests=base, repeat=0) == []
