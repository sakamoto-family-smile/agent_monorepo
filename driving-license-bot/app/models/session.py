"""セッションドメインモデル。"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class QuizMode(StrEnum):
    """ミニテスト or 模擬試験。"""

    MINI = "mini"
    MOCK_PROVISIONAL = "mock_provisional"
    MOCK_FULL = "mock_full"


class SessionState(StrEnum):
    AWAITING_ANSWER = "awaiting_answer"
    IDLE = "idle"
    COMPLETED = "completed"


def _now() -> datetime:
    return datetime.now(UTC)


class Session(BaseModel):
    """`/users/{internal_uid}/sessions/{session_id}` を表す。

    Phase 1 では「直前に出した 1 問」のみを保持する最小実装。
    模擬試験モード（複数問の連続出題）は Phase 5 で本実装。
    """

    internal_uid: str
    session_id: str
    mode: QuizMode = QuizMode.MINI
    state: SessionState = SessionState.IDLE
    current_question_id: str | None = None
    current_question_version: int | None = None
    started_at: datetime = Field(default_factory=_now)
    expires_at: datetime | None = None
