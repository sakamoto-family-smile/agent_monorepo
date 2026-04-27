"""GenerationPipeline を N 件回し、合格分を question_bank に書き込むランナー。

設計（DESIGN.md §3.1.3 / §11 Phase 5）:
- 各サイクルの outcome を集計し BatchSummary として返す
- 例外発生時もサイクルを継続（1 件失敗で全体停止しない）
- analytics-platform に batch_started / batch_completed を emit
- 完了後にプール枯渇チェック → 運営者通知のためのフラグを返す
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.agent import (
    GenerationPipeline,
    GenerationRequest,
    PipelineOutcome,
    PipelineResult,
)
from app.instrumentation.events import (
    emit_business_event,
    emit_error_event,
)
from app.repositories.question_bank import QuestionBankRepo

logger = logging.getLogger(__name__)


@dataclass
class OutcomeStat:
    """1 outcome あたりの集計結果。"""

    outcome: str
    count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0


@dataclass
class BatchSummary:
    total_requested: int
    total_processed: int = 0
    total_errors: int = 0
    by_outcome: dict[str, int] = field(default_factory=dict)
    by_category: dict[str, int] = field(default_factory=dict)
    by_goal: dict[str, int] = field(default_factory=dict)
    pool_count_before: int | None = None
    pool_count_after: int | None = None
    pool_low_alert: bool = False
    error_messages: list[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """REJECTED 以外の outcome 割合。"""
        if self.total_processed == 0:
            return 0.0
        rejected = self.by_outcome.get(PipelineOutcome.REJECTED.value, 0)
        return (self.total_processed - rejected) / self.total_processed


class GenerationRunner:
    """1 バッチ実行を司るオーケストレータ。

    pipeline は `store_on_pass=True` で渡すこと（合格分を bank に書き戻すため）。
    """

    def __init__(
        self,
        pipeline: GenerationPipeline,
        question_bank: QuestionBankRepo,
        *,
        pool_min_size: int = 30,
    ) -> None:
        self._pipeline = pipeline
        self._bank = question_bank
        self._pool_min_size = pool_min_size

    async def run(self, plan: Iterable[GenerationRequest]) -> BatchSummary:
        plan_list = list(plan)
        summary = BatchSummary(total_requested=len(plan_list))

        # 開始時のプール状態
        try:
            summary.pool_count_before = await self._bank.count(
                status="needs_review"
            ) + await self._bank.count(status="published")
        except Exception:  # noqa: BLE001
            logger.exception("failed to read pool count before batch")

        emit_business_event(
            event_name="batch_started",
            properties={
                "total_requested": summary.total_requested,
                "pool_count_before": summary.pool_count_before,
            },
        )

        outcome_counter: Counter[str] = Counter()
        category_counter: Counter[str] = Counter()
        goal_counter: Counter[str] = Counter()

        for idx, request in enumerate(plan_list):
            try:
                result = await self._pipeline.run(request)
            except Exception as exc:  # noqa: BLE001
                summary.total_errors += 1
                summary.error_messages.append(
                    f"[{idx}] {type(exc).__name__}: {exc}"
                )
                emit_error_event(
                    error_type="batch_pipeline_exception",
                    error_message=str(exc),
                    properties={"index": idx, "request": request.model_dump()},
                )
                logger.exception("pipeline raised in batch index=%d", idx)
                continue

            summary.total_processed += 1
            outcome_counter[result.outcome.value] += 1
            category_counter[request.category] += 1
            goal_counter[request.goal] += 1
            self._emit_per_question_events(result, request)

        summary.by_outcome = dict(outcome_counter)
        summary.by_category = dict(category_counter)
        summary.by_goal = dict(goal_counter)

        # 完了時のプール状態 + 枯渇判定
        try:
            summary.pool_count_after = await self._bank.count(
                status="needs_review"
            ) + await self._bank.count(status="published")
            summary.pool_low_alert = (
                summary.pool_count_after is not None
                and summary.pool_count_after < self._pool_min_size
            )
        except Exception:  # noqa: BLE001
            logger.exception("failed to read pool count after batch")

        emit_business_event(
            event_name="batch_completed",
            properties={
                "total_requested": summary.total_requested,
                "total_processed": summary.total_processed,
                "total_errors": summary.total_errors,
                "by_outcome": summary.by_outcome,
                "pool_count_before": summary.pool_count_before,
                "pool_count_after": summary.pool_count_after,
                "pool_low_alert": summary.pool_low_alert,
                "success_rate": summary.success_rate,
            },
        )
        if summary.pool_low_alert:
            emit_business_event(
                event_name="pool_low_alert",
                properties={
                    "current": summary.pool_count_after,
                    "min": self._pool_min_size,
                },
            )

        return summary

    def _emit_per_question_events(
        self, result: PipelineResult, request: GenerationRequest
    ) -> None:
        """1 問あたりの business_event を emit（DESIGN.md §15.1.4 と整合）。

        outcome 種別ごとに細分化することで mart_generation_health の集計精度
        を上げる（成功率・カテゴリ別品質・cross-check 不一致頻度）。
        """
        if result.question is None:
            # generation 失敗（実際には GenerationRunner.run で例外捕捉済みのため通常来ない）
            return

        common = {
            "question_id": result.question.id,
            "category": request.category,
            "goal": request.goal,
            "difficulty": request.difficulty,
            "outcome": result.outcome.value,
        }

        emit_business_event(
            event_name="question_drafted",
            properties=common
            | {
                "input_tokens": result.generation.input_tokens
                if result.generation
                else 0,
                "output_tokens": result.generation.output_tokens
                if result.generation
                else 0,
                "cache_read_input_tokens": result.generation.cache_read_input_tokens
                if result.generation
                else 0,
            },
        )

        if result.fact_check is not None:
            emit_business_event(
                event_name=(
                    "fact_check_passed" if result.fact_check.passed
                    else "fact_check_rejected"
                ),
                properties=common
                | {
                    "score": result.fact_check.score,
                    "issues": result.fact_check.issue_codes,
                },
            )

        if result.dedup is not None:
            emit_business_event(
                event_name=(
                    "dedup_rejected" if result.dedup.is_duplicate else "dedup_passed"
                ),
                properties=common
                | {
                    "best_score": result.dedup.best_score,
                    "threshold": result.dedup.threshold,
                },
            )

        if result.quality_review is not None:
            verdict = result.quality_review.verdict
            event_name = (
                "quality_review_approved" if verdict == "approve"
                else "quality_review_rejected" if verdict == "reject"
                else "quality_review_needs_human"
            )
            emit_business_event(
                event_name=event_name,
                properties=common
                | {
                    "overall_score": result.quality_review.overall_score,
                    "factual_accuracy": result.quality_review.factual_accuracy,
                    "verdict": verdict,
                    "input_tokens": result.quality_review.input_tokens,
                    "output_tokens": result.quality_review.output_tokens,
                },
            )

        # 公開判定
        if result.outcome == PipelineOutcome.APPROVED:
            emit_business_event(event_name="question_published", properties=common)
        elif result.outcome == PipelineOutcome.NEEDS_HUMAN_REVIEW:
            emit_business_event(event_name="question_queued_for_review", properties=common)


__all__ = ["BatchSummary", "GenerationRunner", "OutcomeStat"]
