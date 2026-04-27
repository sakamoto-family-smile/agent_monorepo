"""リポジトリ層（Protocol + in-memory + Firestore 実装）。

Phase 1.5 で Firestore 実装を追加。env `REPOSITORY_BACKEND` で切替（`memory` /
`firestore`）。詳細は `app.repositories.bundle.build_repo_bundle` を参照。
"""

from app.repositories.bundle import RepoBundleImpl, build_repo_bundle
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
    "RepoBundleImpl",
    "SessionRepo",
    "UserRepo",
    "build_repo_bundle",
    "load_question_pool",
]
