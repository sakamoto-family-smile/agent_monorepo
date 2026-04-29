"""Question Repository — 問題本文 / 解説 / sources を保存する。

Phase 2-C2 で追加。pgvector の StoredQuestion (dedup メタ + embedding) と
分離する設計（INFRASTRUCTURE.md §3.11）:

- pgvector: question_id + body_hash + embedding + status + meta（重複検査用）
- Firestore: 完全な Question pydantic モデル（本文 + 解説 + sources）

レビュー UI では question_id をキーに pgvector → status / メタ、Firestore →
本文 / 解説 / sources をそれぞれ取得する。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.models import Question


@runtime_checkable
class QuestionRepo(Protocol):
    """問題本文 (full Question) の永続化。"""

    async def upsert(self, question: Question) -> None: ...

    async def get(self, question_id: str) -> Question | None: ...

    async def delete(self, question_id: str) -> None: ...


class InMemoryQuestionRepo:
    """テスト・開発用 in-memory 実装。"""

    def __init__(self) -> None:
        self._store: dict[str, Question] = {}

    async def upsert(self, question: Question) -> None:
        # pydantic v2 は immutable では無いが、保存時は明示 copy で副作用を避ける
        self._store[question.id] = question.model_copy()

    async def get(self, question_id: str) -> Question | None:
        q = self._store.get(question_id)
        return q.model_copy() if q else None

    async def delete(self, question_id: str) -> None:
        self._store.pop(question_id, None)


__all__ = ["InMemoryQuestionRepo", "QuestionRepo"]
