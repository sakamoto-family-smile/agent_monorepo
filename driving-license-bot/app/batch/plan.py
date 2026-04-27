"""バッチ生成計画（どんな request を何件回すか）。

Phase 2-E はシンプルな round-robin。Phase 5+ で `question_bank.count` から
ギャップを埋める優先度生成に発展させる。
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable

from app.agent import GenerationRequest

# 学科試験で出題され得る現実的な軸の組合せ。Phase 2-E はカテゴリと goal の
# 二軸で round-robin。difficulty は standard 固定（advanced は Phase 4+）。
DEFAULT_CATEGORIES: tuple[str, ...] = ("rules", "signs", "manners", "hazard")
DEFAULT_GOALS: tuple[str, ...] = ("provisional", "full")


def build_round_robin_plan(
    *,
    total: int,
    categories: Iterable[str] = DEFAULT_CATEGORIES,
    goals: Iterable[str] = DEFAULT_GOALS,
    difficulty: str = "standard",
) -> list[GenerationRequest]:
    """カテゴリ × goal の組合せを round-robin で `total` 件返す。

    例: total=4, categories=("rules","signs"), goals=("provisional","full")
    →   rules/provisional, signs/full, rules/full, signs/provisional, ...
    """
    if total <= 0:
        return []
    cats = list(categories)
    gls = list(goals)
    if not cats or not gls:
        raise ValueError("categories and goals must be non-empty")
    # zip_longest 風に組合せを循環させ total 件取り出す
    combos = list(itertools.product(cats, gls))
    plan: list[GenerationRequest] = []
    for i in range(total):
        cat, goal = combos[i % len(combos)]
        plan.append(
            GenerationRequest(
                goal=goal,
                category=cat,
                difficulty=difficulty,
            )
        )
    return plan


def build_targeted_plan(
    *,
    requests: Iterable[GenerationRequest],
    repeat: int = 1,
) -> list[GenerationRequest]:
    """指定の request を `repeat` 倍する（運営者が苦手分野を多めに生成したい時）。"""
    if repeat <= 0:
        return []
    base = list(requests)
    return [r.model_copy() for r in base for _ in range(repeat)]


__all__ = [
    "DEFAULT_CATEGORIES",
    "DEFAULT_GOALS",
    "build_round_robin_plan",
    "build_targeted_plan",
]
