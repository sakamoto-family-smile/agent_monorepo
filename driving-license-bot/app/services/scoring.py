"""採点と回答履歴の更新ロジック。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import NamedTuple

from app.models import AnswerHistory, Question
from app.repositories.protocols import AnswerHistoryRepo


class ScoringResult(NamedTuple):
    correct: bool
    correct_index: int
    chosen_index: int
    explanation: str
    history_after: AnswerHistory


class ScoringService:
    def __init__(self, answer_histories: AnswerHistoryRepo) -> None:
        self._histories = answer_histories

    async def grade_and_record(
        self,
        *,
        internal_uid: str,
        question: Question,
        chosen_index: int,
    ) -> ScoringResult:
        """採点して `answer_history` を更新する。"""
        is_correct = chosen_index == question.correct
        now = datetime.now(UTC)

        existing = await self._histories.get(internal_uid, question.id)
        if existing is None:
            history = AnswerHistory(
                internal_uid=internal_uid,
                question_id=question.id,
                first_answered_at=now,
                last_answered_at=now,
                last_correct=is_correct,
                last_chosen=chosen_index,
                attempt_count=1,
                correct_count=1 if is_correct else 0,
                last_question_version=question.version,
                mastery_level=1 if is_correct else 0,
            )
        else:
            history = existing.model_copy(
                update={
                    "last_answered_at": now,
                    "last_correct": is_correct,
                    "last_chosen": chosen_index,
                    "attempt_count": existing.attempt_count + 1,
                    "correct_count": existing.correct_count + (1 if is_correct else 0),
                    "last_question_version": question.version,
                    "mastery_level": _next_mastery(
                        existing.mastery_level, is_correct
                    ),
                }
            )
        await self._histories.upsert(history)
        return ScoringResult(
            correct=is_correct,
            correct_index=question.correct,
            chosen_index=chosen_index,
            explanation=question.explanation,
            history_after=history,
        )


def _next_mastery(current: int, is_correct: bool) -> int:
    """SM-2 風の簡易習熟度遷移（Phase 6 で本実装する）。

    Phase 1 の用途は復習モードへの素材データ蓄積のみで、ロジックの精緻化は後段。
    """
    if is_correct:
        return min(current + 1, 5)
    return max(current - 1, 0)
