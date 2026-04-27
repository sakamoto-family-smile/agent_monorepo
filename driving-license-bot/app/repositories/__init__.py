"""リポジトリ層（Protocol + in-memory 実装）。

Phase 1 は in-memory 実装のみ。Phase 2 で Firestore 実装を別ファイル
（`firestore_user_repo.py` 等）に追加して同一 Protocol を満たす。
"""

from app.repositories.in_memory import (
    InMemoryAnswerHistoryRepo,
    InMemoryLineUserIndexRepo,
    InMemoryRepoBundle,
    InMemorySessionRepo,
    InMemoryUserRepo,
)
from app.repositories.protocols import (
    AnswerHistoryRepo,
    LineUserIndexRepo,
    RepoBundle,
    SessionRepo,
    UserRepo,
)
from app.repositories.question_pool import QuestionPool, load_question_pool

__all__ = [
    "AnswerHistoryRepo",
    "InMemoryAnswerHistoryRepo",
    "InMemoryLineUserIndexRepo",
    "InMemoryRepoBundle",
    "InMemorySessionRepo",
    "InMemoryUserRepo",
    "LineUserIndexRepo",
    "QuestionPool",
    "RepoBundle",
    "SessionRepo",
    "UserRepo",
    "load_question_pool",
]
