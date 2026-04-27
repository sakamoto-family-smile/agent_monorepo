"""問題ドメインモデル。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class QuestionFormat(StrEnum):
    CHOICE4 = "choice4"
    TRUE_FALSE = "true_false"


class SourceType(StrEnum):
    LAW = "law"
    KYOUSOKU = "kyousoku"
    SIGN_ORDER = "sign_order"


class Source(BaseModel):
    """問題の根拠情報（必須）。"""

    type: SourceType
    title: str
    url: str
    quoted_text: str | None = None
    page: int | None = None


class Choice(BaseModel):
    index: int = Field(ge=0)
    text: str


class Question(BaseModel):
    """問題マスター。

    DESIGN.md §5 のスキーマに準拠。Phase 1 では `applicable_goals`、`sources`、
    正解番号 `correct` を必須項目として扱う。
    """

    id: str
    version: int = 1
    body: str
    format: QuestionFormat
    choices: list[Choice]
    correct: int = Field(ge=0)
    explanation: str
    applicable_goals: list[str]  # ["provisional"], ["full"], ["provisional", "full"]
    difficulty: str = "standard"  # basic | standard | advanced
    category: str = "rules"  # signs | rules | manners | hazard
    sources: list[Source]

    @model_validator(mode="after")
    def _validate(self) -> Question:
        if not self.choices:
            raise ValueError("choices must not be empty")
        # correct インデックスは choices の範囲内
        if self.correct < 0 or self.correct >= len(self.choices):
            raise ValueError(
                f"correct={self.correct} is out of range for {len(self.choices)} choices"
            )
        if self.format is QuestionFormat.TRUE_FALSE and len(self.choices) != 2:
            raise ValueError("true_false format must have exactly 2 choices")
        if self.format is QuestionFormat.CHOICE4 and len(self.choices) != 4:
            raise ValueError("choice4 format must have exactly 4 choices")
        if not self.sources:
            raise ValueError("sources must not be empty (DESIGN.md §0.3 / §5)")
        if not self.applicable_goals:
            raise ValueError("applicable_goals must not be empty")
        for g in self.applicable_goals:
            if g not in {"provisional", "full"}:
                raise ValueError(f"invalid goal: {g}")
        return self

    def matches_goal(self, goal: str) -> bool:
        return goal in self.applicable_goals
