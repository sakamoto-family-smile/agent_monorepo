"""ReviewService — bank (status) と repo (本文) を結合してレビュー UI に提供。

C2 で導入。pgvector / Firestore 両方が無くても in-memory で動かせる構成
（テスト容易性）。アプリ起動時に DI で実装が差し替わる。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.models import Question
from app.repositories.question_bank import StoredQuestion
from app.repositories.question_bank.protocol import QuestionBankRepo
from app.repositories.question_repo import QuestionRepo

logger = logging.getLogger(__name__)


STATUS_NEEDS_REVIEW = "needs_review"
STATUS_PUBLISHED = "published"
STATUS_REJECTED = "rejected"


@dataclass(frozen=True)
class ReviewItem:
    """レビュー UI で 1 件を表現する combined view。"""

    stored: StoredQuestion
    question: Question | None  # 本文未保存なら None（旧 pipeline で生成された分）

    @property
    def question_id(self) -> str:
        return self.stored.question_id

    @property
    def has_body(self) -> bool:
        return self.question is not None


class ReviewService:
    def __init__(
        self,
        *,
        bank: QuestionBankRepo,
        repo: QuestionRepo,
    ) -> None:
        self._bank = bank
        self._repo = repo

    async def list_queue(
        self, *, status: str = STATUS_NEEDS_REVIEW, limit: int = 50
    ) -> list[ReviewItem]:
        stored_list = await self._bank.list_by_status(status, limit=limit)
        items: list[ReviewItem] = []
        for s in stored_list:
            q = await self._repo.get(s.question_id)
            items.append(ReviewItem(stored=s, question=q))
        return items

    async def get_detail(self, question_id: str) -> ReviewItem | None:
        stored = await self._bank.get(question_id)
        if stored is None:
            return None
        question = await self._repo.get(question_id)
        return ReviewItem(stored=stored, question=question)

    async def approve(self, question_id: str) -> bool:
        ok = await self._bank.update_status(question_id, STATUS_PUBLISHED)
        return ok

    async def reject(self, question_id: str) -> bool:
        ok = await self._bank.update_status(question_id, STATUS_REJECTED)
        return ok


__all__ = [
    "STATUS_NEEDS_REVIEW",
    "STATUS_PUBLISHED",
    "STATUS_REJECTED",
    "ReviewItem",
    "ReviewService",
]
