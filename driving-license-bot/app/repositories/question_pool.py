"""問題プール。

Phase 1: シード JSON からの静的読み込み (`QuestionPool`)
Phase 2-X1: bank (pgvector) + Firestore の published 問題から動的構築
            (`BankBackedQuestionPool`)

`QuizService` は Protocol `QuestionPoolLike` 越しに pool を受け取るので、
2 つの実装は無変更でスワップ可能。
"""

from __future__ import annotations

import json
import logging
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.models import Question

logger = logging.getLogger(__name__)


@runtime_checkable
class QuestionPoolLike(Protocol):
    """quiz_service が要求する pool インタフェース。"""

    def __len__(self) -> int: ...

    def all(self) -> list[Question]: ...

    def get(self, question_id: str) -> Question | None: ...

    def pick(
        self,
        goal: str,
        *,
        exclude_ids: set[str] | None = None,
        rng: random.Random | None = None,
    ) -> Question | None: ...


class QuestionPool:
    """シード JSON から読んだ問題プール（Phase 1 用）。

    Phase 2-X1 で `BankBackedQuestionPool` に差し替えできるよう、本クラスも
    引き続き `QuestionPoolLike` Protocol を満たす。
    """

    def __init__(self, questions: list[Question]) -> None:
        self._questions = list(questions)
        self._by_id = {q.id: q for q in self._questions}

    def __len__(self) -> int:
        return len(self._questions)

    def all(self) -> list[Question]:
        return list(self._questions)

    def get(self, question_id: str) -> Question | None:
        return self._by_id.get(question_id)

    def pick(
        self,
        goal: str,
        *,
        exclude_ids: set[str] | None = None,
        rng: random.Random | None = None,
    ) -> Question | None:
        """`goal` 適合の問題からランダムに 1 問抽出。

        - `exclude_ids` に含まれるものは除外（直近出題分の重複回避）
        - 全件除外された場合は除外を無視して再抽選（プール 30 問の Phase 1 制約上）
        """
        rng = rng or random.SystemRandom()
        exclude_ids = exclude_ids or set()
        candidates = [
            q for q in self._questions if q.matches_goal(goal) and q.id not in exclude_ids
        ]
        if not candidates:
            candidates = [q for q in self._questions if q.matches_goal(goal)]
        if not candidates:
            return None
        return rng.choice(candidates)


def load_question_pool(path: str | Path) -> QuestionPool:
    """シード JSON を読み込み QuestionPool を返す。"""
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    questions = [Question.model_validate(item) for item in raw]
    return QuestionPool(questions)


class BankBackedQuestionPool:
    """pgvector (status=published) + Firestore 本文から動的構築するプール。

    起動時 + 一定 TTL 経過時に `refresh()` を呼んで cache を再構築する。
    pick / get は cache 上の同期操作で完結（QuizService から sync 呼び出し可能）。

    cache TTL を超えた状態で pick を呼んだ場合は古い cache を返す（pick が sync の
    ため）。本番では FastAPI lifespan + 定期 refresh task で TTL 内に保つ運用。

    Parameters
    ----------
    bank: QuestionBankRepo
        list_by_status('published', limit=N) を取れる pgvector / InMemory 実装
    repo: QuestionRepo
        本文 (Question pydantic) を取得する Firestore / InMemory 実装
    cache_size: int
        bank から取得する published 問題の最大件数 (default 500)
    """

    def __init__(
        self,
        bank,
        repo,
        *,
        cache_size: int = 500,
    ) -> None:
        self._bank = bank
        self._repo = repo
        self._cache_size = cache_size
        self._questions: list[Question] = []
        self._by_id: dict[str, Question] = {}
        self._loaded_at: datetime | None = None

    @property
    def loaded_at(self) -> datetime | None:
        return self._loaded_at

    async def refresh(self) -> int:
        """bank + repo から最新の published 問題を読み直し cache を入れ替える。

        body 取得失敗（repo に未登録）はスキップしてカウントする。
        """
        stored_list = await self._bank.list_by_status(
            "published", limit=self._cache_size
        )
        questions: list[Question] = []
        missing_body = 0
        for s in stored_list:
            q = await self._repo.get(s.question_id)
            if q is None:
                missing_body += 1
                continue
            questions.append(q)
        self._questions = questions
        self._by_id = {q.id: q for q in questions}
        self._loaded_at = datetime.now(UTC)
        logger.info(
            "BankBackedQuestionPool refreshed: published=%d cached=%d missing_body=%d",
            len(stored_list),
            len(questions),
            missing_body,
        )
        return len(questions)

    def __len__(self) -> int:
        return len(self._questions)

    def all(self) -> list[Question]:
        return list(self._questions)

    def get(self, question_id: str) -> Question | None:
        return self._by_id.get(question_id)

    def pick(
        self,
        goal: str,
        *,
        exclude_ids: set[str] | None = None,
        rng: random.Random | None = None,
    ) -> Question | None:
        """`goal` 適合の問題からランダムに 1 問抽出（QuestionPool と同 interface）。"""
        rng = rng or random.SystemRandom()
        exclude_ids = exclude_ids or set()
        candidates = [
            q for q in self._questions if q.matches_goal(goal) and q.id not in exclude_ids
        ]
        if not candidates:
            candidates = [q for q in self._questions if q.matches_goal(goal)]
        if not candidates:
            return None
        return rng.choice(candidates)


__all__ = [
    "BankBackedQuestionPool",
    "QuestionPool",
    "QuestionPoolLike",
    "load_question_pool",
]
