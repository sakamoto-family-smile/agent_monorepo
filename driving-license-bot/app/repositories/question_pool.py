"""問題プール（Phase 1 はシード JSON からの静的読み込み）。"""

from __future__ import annotations

import json
import random
from pathlib import Path

from app.models import Question


class QuestionPool:
    """シード JSON から読んだ問題プール。

    Phase 2 で Cloud SQL pgvector 経由のプールに差し替える際は、`pick` の
    インタフェースだけ守れば呼び出し側は無変更。
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
