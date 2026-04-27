"""Quality Reviewer Agent — 別系列 LLM (Gemini) による cross-check。

Question Generator が Claude である一方、Quality Reviewer は Gemini を使うことで
共通モード失敗を検出可能にする（DESIGN.md §3.2）。

判定（verdict）:
- `approve`: 自動公開可
- `reject`: 失敗パターンを記録、再生成
- `needs_human_review`: review-admin-ui の人間レビューキューへ
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.agent.errors import GenerationParseError
from app.agent.llm_client import LLMClient
from app.agent.prompts import quality_reviewer as prompts
from app.agent.question_generator import _extract_json_text
from app.config import settings
from app.models import Question

logger = logging.getLogger(__name__)


REQUIRED_KEYS = (
    "overall_score",
    "factual_accuracy",
    "difficulty_appropriate",
    "wording_natural",
    "non_misleading",
    "citation_relevance",
    "verdict",
)

VALID_VERDICTS = ("approve", "reject", "needs_human_review")


@dataclass
class QualityReviewResult:
    overall_score: float
    factual_accuracy: float
    difficulty_appropriate: float
    wording_natural: float
    non_misleading: float
    citation_relevance: float
    verdict: str
    reasons: list[str]
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


def _coerce_score(v: object) -> float:
    """0.0〜1.0 にクランプ。文字列で来ても float に通す。"""
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f


class QualityReviewer:
    def __init__(self, llm: LLMClient, *, max_retries: int = 1) -> None:
        self._llm = llm
        self._max_retries = max(0, max_retries)

    def review(self, question: Question) -> QualityReviewResult:
        user = prompts.build_user_prompt(question)
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            response = self._llm.generate(
                system=prompts.SYSTEM_PROMPT,
                user=user,
                max_tokens=settings.agent_max_tokens,
                temperature=settings.agent_temperature,
                cache_system=True,
            )
            try:
                json_text = _extract_json_text(response.text)
                data = json.loads(json_text)
            except (json.JSONDecodeError, GenerationParseError) as exc:
                last_error = exc
                logger.warning(
                    "reviewer JSON parse failed (attempt %d/%d): %s",
                    attempt + 1,
                    self._max_retries + 1,
                    exc,
                )
                continue
            try:
                result = self._materialize(data, response.model, response.input_tokens, response.output_tokens)
            except ValueError as exc:
                last_error = exc
                logger.warning(
                    "reviewer schema validation failed (attempt %d/%d): %s",
                    attempt + 1,
                    self._max_retries + 1,
                    exc,
                )
                continue
            return result

        raise GenerationParseError(
            f"quality reviewer failed after retries: {last_error}"
        )

    def _materialize(
        self,
        data: dict,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> QualityReviewResult:
        missing = [k for k in REQUIRED_KEYS if k not in data]
        if missing:
            raise ValueError(f"reviewer JSON missing keys: {missing}")
        verdict = str(data["verdict"])
        if verdict not in VALID_VERDICTS:
            raise ValueError(
                f"invalid verdict={verdict!r}; must be one of {VALID_VERDICTS}"
            )
        reasons = data.get("reasons") or []
        if not isinstance(reasons, list):
            reasons = [str(reasons)]
        return QualityReviewResult(
            overall_score=_coerce_score(data["overall_score"]),
            factual_accuracy=_coerce_score(data["factual_accuracy"]),
            difficulty_appropriate=_coerce_score(data["difficulty_appropriate"]),
            wording_natural=_coerce_score(data["wording_natural"]),
            non_misleading=_coerce_score(data["non_misleading"]),
            citation_relevance=_coerce_score(data["citation_relevance"]),
            verdict=verdict,
            reasons=[str(r) for r in reasons][:5],
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


__all__ = ["QualityReviewResult", "QualityReviewer"]
