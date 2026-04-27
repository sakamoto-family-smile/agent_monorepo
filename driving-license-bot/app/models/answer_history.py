"""回答履歴ドメインモデル。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AnswerHistory(BaseModel):
    """`/users/{internal_uid}/answer_history/{question_id}` を表す。

    DESIGN.md §8.2 に準拠。Phase 1 ではフィールドの populate のみ行い、
    復習モード機能（Phase 6+）の本実装まで「直近 N 件除外 / 誤答加重」で活用する。
    """

    internal_uid: str
    question_id: str
    first_answered_at: datetime
    last_answered_at: datetime
    last_correct: bool
    last_chosen: int = Field(ge=0)
    attempt_count: int = Field(ge=1)
    correct_count: int = Field(ge=0)
    last_question_version: int = Field(ge=1)
    mastery_level: int = Field(ge=0, le=5, default=0)
    next_due_at: datetime | None = None
