"""agent 入出力モデル。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models import Question


class GenerationRequest(BaseModel):
    """Question Generator への入力。

    `goal` / `category` / `difficulty` はプール補充の管理側から指定する。
    `topic_hint` は任意のフリーテキスト（例: 「一時停止」「高速道路の最低速度」）。
    """

    goal: str = Field(pattern=r"^(provisional|full)$")
    category: str = Field(pattern=r"^(signs|rules|manners|hazard)$")
    difficulty: str = Field(pattern=r"^(basic|standard|advanced)$", default="standard")
    topic_hint: str | None = None


class GenerationResult(BaseModel):
    """Question Generator の戻り値。

    `question` は LLM 生成 + pydantic 検証済み（schema 違反は raise されている）。
    `metadata` は生成時の input/output トークン数等を保持し、analytics emit や
    コスト分析に使う。
    """

    question: Question
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


__all__ = ["GenerationRequest", "GenerationResult"]
