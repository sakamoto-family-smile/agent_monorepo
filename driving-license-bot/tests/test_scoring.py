"""ScoringService のテスト。"""

from __future__ import annotations

import pytest

from app.models import Question, QuestionFormat
from app.repositories import InMemoryRepoBundle
from app.services.scoring import ScoringService


def _q(correct: int = 0, qid: str = "q1") -> Question:
    return Question.model_validate(
        {
            "id": qid,
            "version": 1,
            "body": "test",
            "format": QuestionFormat.TRUE_FALSE,
            "choices": [
                {"index": 0, "text": "正しい"},
                {"index": 1, "text": "誤り"},
            ],
            "correct": correct,
            "explanation": "explanation",
            "applicable_goals": ["provisional", "full"],
            "sources": [
                {
                    "type": "law",
                    "title": "test",
                    "url": "https://example.com",
                }
            ],
        }
    )


@pytest.mark.asyncio
async def test_first_correct_answer_creates_history() -> None:
    bundle = InMemoryRepoBundle()
    svc = ScoringService(bundle.answer_histories)
    q = _q(correct=0)

    res = await svc.grade_and_record(
        internal_uid="u1", question=q, chosen_index=0
    )

    assert res.correct is True
    assert res.correct_index == 0
    history = await bundle.answer_histories.get("u1", q.id)
    assert history is not None
    assert history.attempt_count == 1
    assert history.correct_count == 1
    assert history.last_correct is True
    assert history.mastery_level == 1


@pytest.mark.asyncio
async def test_wrong_answer_decrements_mastery() -> None:
    bundle = InMemoryRepoBundle()
    svc = ScoringService(bundle.answer_histories)
    q = _q(correct=0)

    # 最初に正解で mastery=1
    await svc.grade_and_record(internal_uid="u1", question=q, chosen_index=0)
    # 次に間違えると mastery=0 に下がり、attempt は 2
    res2 = await svc.grade_and_record(
        internal_uid="u1", question=q, chosen_index=1
    )
    assert res2.correct is False
    history = await bundle.answer_histories.get("u1", q.id)
    assert history is not None
    assert history.attempt_count == 2
    assert history.correct_count == 1
    assert history.last_correct is False
    assert history.mastery_level == 0


@pytest.mark.asyncio
async def test_mastery_capped_at_5() -> None:
    bundle = InMemoryRepoBundle()
    svc = ScoringService(bundle.answer_histories)
    q = _q(correct=0)
    for _ in range(10):
        await svc.grade_and_record(internal_uid="u1", question=q, chosen_index=0)
    history = await bundle.answer_histories.get("u1", q.id)
    assert history is not None
    assert history.mastery_level == 5
