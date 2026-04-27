"""生成パイプラインのオーケストレータ。

draft → fact-check → quality-review → 公開判定 の 1 段サイクル。

判定マトリクス（DESIGN.md §3.2 / §10.3）:

    fact_check.passed | reviewer.verdict | overall outcome
    ────────────────────────────────────────────────────────
    False             | (any)            | rejected
    True              | reject           | rejected
    True              | needs_human      | needs_human_review
    True              | approve          | needs_human_review (Phase 1)
                                         | approved (Phase 2 以降の自動公開ルールで分岐)

Phase 2-C は **常に needs_human_review** を返す保守的設定。Phase 3+ で
自動公開しきい値を導入する。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum

from app.agent.fact_checker import FactChecker, FactCheckResult
from app.agent.models import GenerationRequest, GenerationResult
from app.agent.quality_reviewer import QualityReviewer, QualityReviewResult
from app.agent.question_generator import QuestionGenerator
from app.models import Question

logger = logging.getLogger(__name__)


class PipelineOutcome(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


@dataclass
class PipelineResult:
    """1 サイクルの結果。"""

    outcome: PipelineOutcome
    question: Question | None
    generation: GenerationResult | None = None
    fact_check: FactCheckResult | None = None
    quality_review: QualityReviewResult | None = None
    rejection_reasons: list[str] = field(default_factory=list)

    @property
    def passed_all(self) -> bool:
        """ファクトチェックとレビュアー両方が完了し、reject ではないか。"""
        return self.outcome != PipelineOutcome.REJECTED


class GenerationPipeline:
    def __init__(
        self,
        generator: QuestionGenerator,
        fact_checker: FactChecker,
        quality_reviewer: QualityReviewer,
        *,
        auto_approve_overall_score: float | None = None,
    ) -> None:
        """
        Parameters
        ----------
        auto_approve_overall_score:
            None の場合、approve verdict であっても needs_human_review に倒す
            （Phase 1 の人間レビュー必須運用）。Phase 3 以降でしきい値を渡し、
            高スコアのみ自動公開する運用に切り替える。
        """
        self._generator = generator
        self._fact_checker = fact_checker
        self._reviewer = quality_reviewer
        self._auto_approve_threshold = auto_approve_overall_score

    def run(self, request: GenerationRequest) -> PipelineResult:
        """1 問生成 → 検証 → レビュー → 判定。例外は呼び出し側で扱う。"""
        # Step 1: generation
        generation = self._generator.generate(request)
        question = generation.question
        logger.info("generated question id=%s", question.id)

        # Step 2: fact check（rule-based、決定的）
        fact_check = self._fact_checker.check(question)
        if not fact_check.passed:
            reasons = [
                f"[fact] {i.code}: {i.message}" for i in fact_check.issues
            ]
            logger.warning(
                "fact check rejected question id=%s reasons=%s",
                question.id,
                fact_check.issue_codes,
            )
            return PipelineResult(
                outcome=PipelineOutcome.REJECTED,
                question=question,
                generation=generation,
                fact_check=fact_check,
                rejection_reasons=reasons,
            )

        # Step 3: quality review（LLM cross-check）
        review = self._reviewer.review(question)
        logger.info(
            "quality review verdict=%s overall=%.3f question id=%s",
            review.verdict,
            review.overall_score,
            question.id,
        )
        if review.verdict == "reject":
            return PipelineResult(
                outcome=PipelineOutcome.REJECTED,
                question=question,
                generation=generation,
                fact_check=fact_check,
                quality_review=review,
                rejection_reasons=[
                    "[review] reject: " + r for r in review.reasons
                ],
            )

        # Step 4: 公開判定
        outcome = self._decide_outcome(review)
        return PipelineResult(
            outcome=outcome,
            question=question,
            generation=generation,
            fact_check=fact_check,
            quality_review=review,
        )

    def _decide_outcome(
        self, review: QualityReviewResult
    ) -> PipelineOutcome:
        """approve verdict かつ overall_score がしきい値超なら自動公開。

        Phase 2-C は `auto_approve_overall_score=None` で常に needs_human_review
        に倒す保守的設定（運用フロー上 1 人レビューが必須）。
        """
        if self._auto_approve_threshold is None:
            return PipelineOutcome.NEEDS_HUMAN_REVIEW
        if (
            review.verdict == "approve"
            and review.overall_score >= self._auto_approve_threshold
        ):
            return PipelineOutcome.APPROVED
        return PipelineOutcome.NEEDS_HUMAN_REVIEW


__all__ = ["GenerationPipeline", "PipelineOutcome", "PipelineResult"]
