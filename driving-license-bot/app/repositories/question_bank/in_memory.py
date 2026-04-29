"""In-memory Question Bank（テスト・開発用）。

cosine 類似度を Python ループで計算する単純実装。Phase 5 で 1 万件を超える
規模になったら pgvector 必須。テストでは数件しか入れないので問題ない。
"""

from __future__ import annotations

import math
from collections import OrderedDict

from app.repositories.question_bank.protocol import (
    SimilarityHit,
    StoredQuestion,
)


def _cosine(a: list[float], b: list[float]) -> float:
    """cosine 類似度。次元不一致時は 0.0 を返す（ハードフェイルしない）。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class InMemoryQuestionBank:
    def __init__(self) -> None:
        # 挿入順を保持（テストで FIFO 期待を持つ場合に便利）
        self._store: OrderedDict[str, StoredQuestion] = OrderedDict()

    async def add(self, question: StoredQuestion) -> None:
        self._store[question.question_id] = question

    async def find_similar(
        self,
        embedding: list[float],
        *,
        top_k: int = 5,
        category: str | None = None,
    ) -> list[SimilarityHit]:
        candidates = self._store.values()
        if category is not None:
            candidates = [q for q in candidates if q.category == category]
        scored = [
            SimilarityHit(stored=q, score=_cosine(embedding, q.embedding))
            for q in candidates
        ]
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:top_k]

    async def find_by_body_hash(self, body_hash: str) -> StoredQuestion | None:
        for q in self._store.values():
            if q.body_hash == body_hash:
                return q
        return None

    async def count(
        self,
        *,
        status: str | None = None,
        applicable_goal: str | None = None,
    ) -> int:
        items = self._store.values()
        if status is not None:
            items = [q for q in items if q.status == status]
        if applicable_goal is not None:
            items = [q for q in items if applicable_goal in q.applicable_goals]
        return len(list(items))

    async def get(self, question_id: str) -> StoredQuestion | None:
        return self._store.get(question_id)

    async def list_by_status(
        self,
        status: str,
        *,
        limit: int = 50,
    ) -> list[StoredQuestion]:
        items = [q for q in self._store.values() if q.status == status]
        items.sort(key=lambda q: q.created_at, reverse=True)
        return items[:limit]

    async def update_status(self, question_id: str, status: str) -> bool:
        existing = self._store.get(question_id)
        if existing is None:
            return False
        # StoredQuestion は dataclass(eq) なので新オブジェクト作成
        from dataclasses import replace

        self._store[question_id] = replace(existing, status=status)
        return True
