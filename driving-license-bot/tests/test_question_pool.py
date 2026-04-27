"""シード問題プールのスキーマ整合性テスト。

DESIGN.md §0.3「全問題に根拠情報を必須化」を保証するための門番として、
全問題が `sources` を 1 件以上持つことをチェックする。
"""

from __future__ import annotations

import pytest

from app.models import Goal, Question, QuestionFormat
from app.repositories.question_pool import QuestionPool


def test_seed_pool_has_30_questions(question_pool: QuestionPool) -> None:
    assert len(question_pool) == 30


def test_every_seed_question_has_at_least_one_source(
    question_pool: QuestionPool,
) -> None:
    for q in question_pool.all():
        assert q.sources, f"question {q.id} must have sources (DESIGN.md §0.3)"
        for src in q.sources:
            assert src.url.startswith("http"), f"{q.id} source url invalid"
            assert src.title, f"{q.id} source title empty"


def test_every_seed_question_has_valid_correct_index(
    question_pool: QuestionPool,
) -> None:
    for q in question_pool.all():
        assert 0 <= q.correct < len(q.choices), q.id


def test_every_seed_question_applies_to_at_least_one_goal(
    question_pool: QuestionPool,
) -> None:
    for q in question_pool.all():
        assert q.applicable_goals, q.id
        for g in q.applicable_goals:
            assert g in {"provisional", "full"}, f"{q.id}: bad goal {g}"


def test_seed_pool_covers_both_goals(question_pool: QuestionPool) -> None:
    """仮免・本免どちらでも出題できるようプールに最低 1 問ずつあること。"""
    has_provisional = any(
        q.matches_goal(Goal.PROVISIONAL.value) for q in question_pool.all()
    )
    has_full = any(q.matches_goal(Goal.FULL.value) for q in question_pool.all())
    assert has_provisional
    assert has_full


def test_pick_respects_goal(question_pool: QuestionPool) -> None:
    """`pick` は goal 適合の問題のみ返す。"""
    for _ in range(50):
        q = question_pool.pick(Goal.FULL.value)
        assert q is not None
        assert Goal.FULL.value in q.applicable_goals


def test_pick_respects_exclude_when_alternatives_exist(
    question_pool: QuestionPool,
) -> None:
    all_for_goal = [
        q.id
        for q in question_pool.all()
        if q.matches_goal(Goal.PROVISIONAL.value)
    ]
    assert len(all_for_goal) >= 2
    exclude = {all_for_goal[0]}
    for _ in range(20):
        picked = question_pool.pick(
            Goal.PROVISIONAL.value, exclude_ids=exclude
        )
        assert picked is not None
        assert picked.id != all_for_goal[0]


def test_question_validation_rejects_missing_sources() -> None:
    with pytest.raises(ValueError, match="sources"):
        Question(
            id="x",
            body="b",
            format=QuestionFormat.TRUE_FALSE,
            choices=[
                {"index": 0, "text": "a"},
                {"index": 1, "text": "b"},
            ],
            correct=0,
            explanation="e",
            applicable_goals=["provisional"],
            sources=[],
        )


def test_question_validation_rejects_out_of_range_correct() -> None:
    with pytest.raises(ValueError, match="correct"):
        Question(
            id="x",
            body="b",
            format=QuestionFormat.TRUE_FALSE,
            choices=[
                {"index": 0, "text": "a"},
                {"index": 1, "text": "b"},
            ],
            correct=5,
            explanation="e",
            applicable_goals=["provisional"],
            sources=[
                {
                    "type": "law",
                    "title": "x",
                    "url": "https://example.com",
                }
            ],
        )
