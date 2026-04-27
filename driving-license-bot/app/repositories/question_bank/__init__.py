"""Question Bank（pgvector ベースの重複検査リポジトリ）。

Protocol を In-memory（テスト・開発）/ Pgvector（本番）どちらでも満たし、
pipeline の dedup ステップで透過的に使う。
"""

from app.repositories.question_bank.in_memory import InMemoryQuestionBank
from app.repositories.question_bank.protocol import (
    QuestionBankRepo,
    SimilarityHit,
    StoredQuestion,
)

__all__ = [
    "InMemoryQuestionBank",
    "QuestionBankRepo",
    "SimilarityHit",
    "StoredQuestion",
]
