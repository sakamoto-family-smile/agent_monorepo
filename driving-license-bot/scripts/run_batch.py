"""Cloud Run Job entry: 問題生成バッチを 1 回実行する。

使い方（ローカル）:
    cd driving-license-bot
    GOOGLE_CLOUD_PROJECT=... uv run python scripts/run_batch.py \
        --total 10 --difficulty standard

Cloud Run Job として:
    gcloud run jobs deploy driving-license-bot-batch \\
        --image=asia-northeast1-docker.pkg.dev/$PROJECT/driving-license-bot/batch:latest \\
        --command=python --args="-m,scripts.run_batch,--total,20"
        ...
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
    LLMClientError,
    QualityReviewer,
    QuestionGenerator,
    build_embedding_client,
    build_llm_client,
    build_reviewer_llm_client,
)
from app.batch import (
    BatchSummary,
    GenerationRunner,
    build_round_robin_plan,
)
from app.config import settings
from app.instrumentation import setup_observability, shutdown_observability
from app.repositories.question_bank import (
    InMemoryQuestionBank,
    QuestionBankRepo,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run question generation batch (1 cycle)")
    p.add_argument(
        "--total",
        type=int,
        default=settings.generation_batch_size,
        help="生成する問題数（既定: GENERATION_BATCH_SIZE）",
    )
    p.add_argument(
        "--difficulty",
        choices=["basic", "standard", "advanced"],
        default="standard",
    )
    p.add_argument(
        "--auto-approve",
        type=float,
        default=None,
        help="overall_score this threshold 以上の approve を自動公開",
    )
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


async def _build_question_bank() -> QuestionBankRepo:
    """env から question_bank backend を選ぶ。"""
    backend = settings.question_bank_backend.lower()
    if backend == "pgvector":
        from app.agent.errors import LLMClientError as _LLMErr
        from app.repositories.question_bank.pgvector_impl import (
            PgvectorQuestionBank,
            build_pgvector_pool,
        )

        if not settings.cloudsql_host:
            raise _LLMErr(
                "CLOUDSQL_HOST is required for question_bank pgvector backend"
            )
        pool = await build_pgvector_pool(
            host=settings.cloudsql_host,
            port=settings.cloudsql_port,
            user=settings.cloudsql_user,
            password=settings.cloudsql_password,
            database=settings.cloudsql_db,
        )
        return PgvectorQuestionBank(pool)
    return InMemoryQuestionBank()


async def _run(args: argparse.Namespace) -> int:
    setup_observability()
    try:
        gen_llm = build_llm_client()
        review_llm = build_reviewer_llm_client()
        embedding_client = build_embedding_client()
    except LLMClientError as exc:
        print(f"failed to build LLM/embedding clients: {exc}", file=sys.stderr)
        await shutdown_observability()
        return 1

    try:
        question_bank = await _build_question_bank()
    except Exception as exc:  # noqa: BLE001
        print(f"failed to build question bank: {exc}", file=sys.stderr)
        await shutdown_observability()
        return 1

    pipeline = GenerationPipeline(
        QuestionGenerator(gen_llm),
        FactChecker(),
        QualityReviewer(review_llm),
        embedding_client=embedding_client,
        question_bank=question_bank,
        dedup_threshold=settings.question_bank_dedup_threshold,
        dedup_top_k=settings.question_bank_top_k,
        auto_approve_overall_score=args.auto_approve,
        store_on_pass=True,
    )

    runner = GenerationRunner(
        pipeline,
        question_bank,
        pool_min_size=settings.question_pool_min_size,
    )

    plan = build_round_robin_plan(total=args.total, difficulty=args.difficulty)
    summary = await runner.run(plan)

    _emit_summary(summary)
    await shutdown_observability()
    # exit code: バッチ全体は成功（個別失敗は summary.total_errors に集約）。
    # 1 件も処理できなかった場合のみ非ゼロを返す。
    return 0 if summary.total_processed > 0 else 2


def _emit_summary(summary: BatchSummary) -> None:
    payload = {
        "total_requested": summary.total_requested,
        "total_processed": summary.total_processed,
        "total_errors": summary.total_errors,
        "by_outcome": summary.by_outcome,
        "by_category": summary.by_category,
        "by_goal": summary.by_goal,
        "pool_count_before": summary.pool_count_before,
        "pool_count_after": summary.pool_count_after,
        "pool_low_alert": summary.pool_low_alert,
        "success_rate": summary.success_rate,
        "errors": summary.error_messages[:10],  # 先頭 10 件のみ
    }
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    return asyncio.run(_run(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
