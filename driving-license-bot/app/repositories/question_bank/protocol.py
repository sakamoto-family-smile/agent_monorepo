"""Question Bank の Protocol と関連 dataclass。

DESIGN.md §3.3 / §13.12 の `question-bank` テーブルに対応。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@dataclass
class StoredQuestion:
    """Question Bank に永続化される 1 件の問題メタ + embedding。

    Question 本体ではなく、dedup や検索に必要な最小フィールドのみ保持する
    （重い `body` / `explanation` 全文は別 Firestore に置く設計）。
    """

    question_id: str
    version: int
    body_hash: str  # body の sha256（厳密一致検出用）
    embedding: list[float]
    applicable_goals: list[str]
    category: str
    difficulty: str
    status: str = "needs_review"  # needs_review | published | archived
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class SimilarityHit:
    """類似度検索の 1 件結果。"""

    stored: StoredQuestion
    score: float  # cosine 類似度、-1.0〜1.0（実用上 0.0〜1.0）

    @property
    def is_exact_match(self) -> bool:
        return self.score >= 0.999


@runtime_checkable
class QuestionBankRepo(Protocol):
    """Question Bank のリポジトリ Protocol。

    Phase 2-D で必要な最小操作のみ。Phase 5 で出題プールとしての検索
    （`pick`）も同じ Protocol に追加する想定。
    """

    async def add(self, question: StoredQuestion) -> None: ...

    async def find_similar(
        self,
        embedding: list[float],
        *,
        top_k: int = 5,
        category: str | None = None,
    ) -> list[SimilarityHit]: ...

    async def find_by_body_hash(self, body_hash: str) -> StoredQuestion | None: ...

    async def count(
        self,
        *,
        status: str | None = None,
        applicable_goal: str | None = None,
    ) -> int: ...

    async def get(self, question_id: str) -> StoredQuestion | None: ...
