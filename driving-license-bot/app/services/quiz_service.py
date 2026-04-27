"""出題サービス（プールから問題を選び、セッションを更新する）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.models import Question, QuizMode, Session, SessionState
from app.repositories.protocols import AnswerHistoryRepo, SessionRepo
from app.repositories.question_pool import QuestionPool


class QuizService:
    """出題のライフサイクルを管理する。

    - `start_question`: ユーザーに次の 1 問を出す（直近出題を除外）
    - `consume_active_session`: 回答受付時にセッションを完了状態に遷移
    """

    def __init__(
        self,
        pool: QuestionPool,
        sessions: SessionRepo,
        answer_histories: AnswerHistoryRepo,
        *,
        recent_exclude_window: int = 5,
    ) -> None:
        self._pool = pool
        self._sessions = sessions
        self._histories = answer_histories
        self._recent_exclude_window = recent_exclude_window

    async def start_question(
        self,
        *,
        internal_uid: str,
        goal: str,
        mode: QuizMode = QuizMode.MINI,
    ) -> tuple[Question, Session] | None:
        """次の問題を選び、セッションを `awaiting_answer` で作成する。

        既に `awaiting_answer` が残っている場合は新規作成せず流用する（Phase 1 制約）。
        """
        recent = await self._histories.list_recent(
            internal_uid, limit=self._recent_exclude_window
        )
        exclude = {h.question_id for h in recent}
        question = self._pool.pick(goal, exclude_ids=exclude)
        if question is None:
            return None

        session_id = str(uuid.uuid4())
        session = Session(
            internal_uid=internal_uid,
            session_id=session_id,
            mode=mode,
            state=SessionState.AWAITING_ANSWER,
            current_question_id=question.id,
            current_question_version=question.version,
            started_at=datetime.now(UTC),
        )
        await self._sessions.upsert(session)
        return question, session

    async def consume_active_session(
        self, internal_uid: str
    ) -> tuple[Session, Question] | None:
        """active session の問題を取得し、状態を `completed` に遷移して保存。"""
        active = await self._sessions.get_active(internal_uid)
        if active is None or active.current_question_id is None:
            return None
        question = self._pool.get(active.current_question_id)
        if question is None:
            return None
        active.state = SessionState.COMPLETED
        await self._sessions.upsert(active)
        return active, question
