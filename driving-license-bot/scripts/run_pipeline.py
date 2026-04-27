"""Generation Pipeline を 1 サイクル走らせて結果 JSON を出力する CLI（手動検証用）。

draft → fact-check → dedup → quality-review → 公開判定 まで通す。

使い方:
    cd driving-license-bot
    GOOGLE_CLOUD_PROJECT=... uv run python scripts/run_pipeline.py \
        --goal full --category rules --difficulty standard

Phase 2-D の CLI は in-memory question_bank で起動。pgvector への接続は
PR E のバッチ実装で行う。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from app.agent import (
    FactChecker,
    GenerationPipeline,
    GenerationRequest,
    LLMClientError,
    PipelineResult,
    QualityReviewer,
    QuestionGenerator,
    build_embedding_client,
    build_llm_client,
    build_reviewer_llm_client,
)
from app.config import settings
from app.repositories.question_bank import InMemoryQuestionBank


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run full generation pipeline once")
    p.add_argument("--goal", choices=["provisional", "full"], required=True)
    p.add_argument(
        "--category",
        choices=["signs", "rules", "manners", "hazard"],
        required=True,
    )
    p.add_argument(
        "--difficulty",
        choices=["basic", "standard", "advanced"],
        default="standard",
    )
    p.add_argument("--topic-hint", default=None)
    p.add_argument(
        "--auto-approve",
        type=float,
        default=None,
        help="overall_score this threshold 以上の approve を自動公開",
    )
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


async def _run(args: argparse.Namespace) -> int:
    try:
        gen_llm = build_llm_client()
        review_llm = build_reviewer_llm_client()
        embedding_client = build_embedding_client()
    except LLMClientError as exc:
        print(f"failed to build LLM/embedding clients: {exc}", file=sys.stderr)
        return 1

    question_bank = InMemoryQuestionBank()

    pipeline = GenerationPipeline(
        QuestionGenerator(gen_llm),
        FactChecker(),
        QualityReviewer(review_llm),
        embedding_client=embedding_client,
        question_bank=question_bank,
        dedup_threshold=settings.question_bank_dedup_threshold,
        dedup_top_k=settings.question_bank_top_k,
        auto_approve_overall_score=args.auto_approve,
    )

    request = GenerationRequest(
        goal=args.goal,
        category=args.category,
        difficulty=args.difficulty,
        topic_hint=args.topic_hint,
    )

    try:
        result = await pipeline.run(request)
    except Exception as exc:  # noqa: BLE001
        print(f"pipeline failed: {exc}", file=sys.stderr)
        return 2
    _emit_payload(result)
    return 0


def _emit_payload(result: PipelineResult) -> None:
    payload = {
        "outcome": result.outcome.value,
        "question": result.question.model_dump(mode="json") if result.question else None,
        "fact_check": (
            {
                "passed": result.fact_check.passed,
                "score": result.fact_check.score,
                "issues": [i.__dict__ for i in result.fact_check.issues],
            }
            if result.fact_check
            else None
        ),
        "dedup": (
            {
                "is_duplicate": result.dedup.is_duplicate,
                "best_score": result.dedup.best_score,
                "threshold": result.dedup.threshold,
                "top_hits": [
                    {
                        "question_id": h.stored.question_id,
                        "score": h.score,
                    }
                    for h in result.dedup.top_hits
                ],
            }
            if result.dedup
            else None
        ),
        "quality_review": (
            {
                "verdict": result.quality_review.verdict,
                "overall_score": result.quality_review.overall_score,
                "factual_accuracy": result.quality_review.factual_accuracy,
                "difficulty_appropriate": result.quality_review.difficulty_appropriate,
                "wording_natural": result.quality_review.wording_natural,
                "non_misleading": result.quality_review.non_misleading,
                "citation_relevance": result.quality_review.citation_relevance,
                "reasons": result.quality_review.reasons,
                "model": result.quality_review.model,
                "input_tokens": result.quality_review.input_tokens,
                "output_tokens": result.quality_review.output_tokens,
            }
            if result.quality_review
            else None
        ),
        "rejection_reasons": result.rejection_reasons,
    }
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    return asyncio.run(_run(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
