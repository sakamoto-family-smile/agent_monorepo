"""生成パイプラインのオーケストレータ。

draft → fact-check → dedup → quality-review → 公開判定 の 1 段サイクル。

判定マトリクス（DESIGN.md §3.2 / §10.3）:

    fact_check.passed | dedup           | reviewer.verdict | outcome
    ────────────────────────────────────────────────────────────────
    False             | (skipped)       | (skipped)        | rejected
    True              | duplicate found | (skipped)        | rejected (duplicate)
    True              | clear           | reject           | rejected
    True              | clear           | needs_human      | needs_human_review
    True              | clear           | approve          | needs_human_review (Phase 1)
                                                            | approved (auto_approve thr 超)

Phase 2-C は **常に needs_human_review** を返す保守的設定。Phase 3+ で
自動公開しきい値を導入する。Phase 2-D で dedup を追加。
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from app.agent.embedding import EmbeddingClient
from app.agent.fact_checker import FactChecker, FactCheckResult
from app.agent.models import GenerationRequest, GenerationResult
from app.agent.quality_reviewer import QualityReviewer, QualityReviewResult
from app.agent.question_generator import QuestionGenerator
from app.models import Question
from app.repositories.question_bank import (
    QuestionBankRepo,
    SimilarityHit,
    StoredQuestion,
)

logger = logging.getLogger(__name__)


class PipelineOutcome(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


@dataclass
class DedupResult:
    """重複検査の結果。"""

    is_duplicate: bool
    top_hits: list[SimilarityHit] = field(default_factory=list)
    threshold: float = 0.92

    @property
    def best_score(self) -> float:
        return self.top_hits[0].score if self.top_hits else 0.0


@dataclass
class PipelineResult:
    """1 サイクルの結果。"""

    outcome: PipelineOutcome
    question: Question | None
    generation: GenerationResult | None = None
    fact_check: FactCheckResult | None = None
    dedup: DedupResult | None = None
    quality_review: QualityReviewResult | None = None
    rejection_reasons: list[str] = field(default_factory=list)

    @property
    def passed_all(self) -> bool:
        return self.outcome != PipelineOutcome.REJECTED


def _body_hash(body: str) -> str:
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


class GenerationPipeline:
    def __init__(
        self,
        generator: QuestionGenerator,
        fact_checker: FactChecker,
        quality_reviewer: QualityReviewer,
        *,
        embedding_client: EmbeddingClient | None = None,
        question_bank: QuestionBankRepo | None = None,
        question_repo: object | None = None,  # Phase 2-C2: QuestionRepo Protocol
        dedup_threshold: float = 0.92,
        dedup_top_k: int = 5,
        auto_approve_overall_score: float | None = None,
        store_on_pass: bool = False,
    ) -> None:
        """
        Parameters
        ----------
        embedding_client / question_bank:
            両方指定された場合のみ dedup ステップが有効化される。片方欠落時は
            dedup をスキップ（後方互換）。Phase 2-D 以降は本番では常に両方
            指定する。
        dedup_threshold:
            cosine 類似度がこれを超えると重複扱い。既定 0.92。
        store_on_pass:
            outcome が REJECTED 以外の場合に question_bank へ書き込むか。
            Phase 2-D は dedup チェックのみ（write は PR E のバッチで一元管理）
            のため既定 False。
        """
        self._generator = generator
        self._fact_checker = fact_checker
        self._reviewer = quality_reviewer
        self._embedding = embedding_client
        self._question_bank = question_bank
        # Phase 2-C2: 本文保存先（Firestore など）。None なら本文未保存（後方互換）
        self._question_repo = question_repo
        self._dedup_threshold = dedup_threshold
        self._dedup_top_k = dedup_top_k
        self._auto_approve_threshold = auto_approve_overall_score
        self._store_on_pass = store_on_pass

    @property
    def _dedup_enabled(self) -> bool:
        return self._embedding is not None and self._question_bank is not None

    async def run(self, request: GenerationRequest) -> PipelineResult:
        """1 問生成 → fact → dedup → review → 判定。例外は呼び出し側で扱う。"""
        # Step 1: generation
        generation = self._generator.generate(request)
        question = generation.question
        logger.info("generated question id=%s", question.id)

        # Step 2: fact check（rule-based、決定的）
        fact_check = self._fact_checker.check(question)
        if not fact_check.passed:
            reasons = [f"[fact] {i.code}: {i.message}" for i in fact_check.issues]
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

        # Step 3: dedup（Phase 2-D 以降、enabled なら必須）
        dedup: DedupResult | None = None
        embedding_vec: list[float] | None = None
        if self._dedup_enabled:
            assert self._embedding is not None and self._question_bank is not None
            embedding_vec = self._embedding.embed(question.body)
            hits = await self._question_bank.find_similar(
                embedding_vec,
                top_k=self._dedup_top_k,
                category=question.category,
            )
            dedup = DedupResult(
                is_duplicate=bool(hits and hits[0].score >= self._dedup_threshold),
                top_hits=hits,
                threshold=self._dedup_threshold,
            )
            if dedup.is_duplicate:
                top = hits[0]
                msg = (
                    f"[dedup] duplicate of {top.stored.question_id} "
                    f"(score={top.score:.3f} >= {self._dedup_threshold})"
                )
                logger.warning(
                    "dedup rejected question id=%s reason=%s", question.id, msg
                )
                return PipelineResult(
                    outcome=PipelineOutcome.REJECTED,
                    question=question,
                    generation=generation,
                    fact_check=fact_check,
                    dedup=dedup,
                    rejection_reasons=[msg],
                )

        # Step 4: quality review（LLM cross-check）
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
                dedup=dedup,
                quality_review=review,
                rejection_reasons=["[review] reject: " + r for r in review.reasons],
            )

        # Step 5: 公開判定
        outcome = self._decide_outcome(review)

        # Step 6 (任意): question_bank へ書き込み
        if self._store_on_pass and self._dedup_enabled and embedding_vec is not None:
            await self._persist(question, embedding_vec, outcome)

        return PipelineResult(
            outcome=outcome,
            question=question,
            generation=generation,
            fact_check=fact_check,
            dedup=dedup,
            quality_review=review,
        )

    def _decide_outcome(self, review: QualityReviewResult) -> PipelineOutcome:
        """approve verdict かつ overall_score がしきい値超なら自動公開。"""
        if self._auto_approve_threshold is None:
            return PipelineOutcome.NEEDS_HUMAN_REVIEW
        if (
            review.verdict == "approve"
            and review.overall_score >= self._auto_approve_threshold
        ):
            return PipelineOutcome.APPROVED
        return PipelineOutcome.NEEDS_HUMAN_REVIEW

    async def _persist(
        self,
        question: Question,
        embedding: list[float],
        outcome: PipelineOutcome,
    ) -> None:
        assert self._question_bank is not None
        status = (
            "published"
            if outcome == PipelineOutcome.APPROVED
            else "needs_review"
        )
        stored = StoredQuestion(
            question_id=question.id,
            version=question.version,
            body_hash=_body_hash(question.body),
            embedding=embedding,
            applicable_goals=list(question.applicable_goals),
            category=question.category,
            difficulty=question.difficulty,
            status=status,
            created_at=datetime.now(UTC),
        )
        await self._question_bank.add(stored)
        # Phase 2-C2: 本文も保存（レビュー UI から読む）。失敗してもパイプライン
        # 全体は止めない（バンクには入っているので最低限の dedup は機能する）。
        if self._question_repo is not None:
            try:
                await self._question_repo.upsert(question)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "question_repo.upsert failed id=%s (continuing)", question.id
                )


__all__ = [
    "DedupResult",
    "GenerationPipeline",
    "PipelineOutcome",
    "PipelineResult",
]
