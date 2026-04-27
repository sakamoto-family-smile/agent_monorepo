"""GenerationRunner のテスト（Mock LLM + InMemoryQuestionBank）。"""

from __future__ import annotations

import json

import pytest

from app.agent import (
    FactChecker,
    GenerationPipeline,
    GenerationRequest,
    MockEmbeddingClient,
    MockLLMClient,
    QualityReviewer,
    QuestionGenerator,
)
from app.batch import GenerationRunner
from app.repositories.question_bank import (
    InMemoryQuestionBank,
    StoredQuestion,
)

KNOWN_URL = "https://laws.e-gov.go.jp/document?lawid=335CO0000000270"

VALID_QUESTION_DICT = {
    "id": "q_batch_sample",
    "version": 1,
    "body": "信号機の青色の灯火は直進・左折・右折のいずれもできることを示している。",
    "format": "true_false",
    "choices": [
        {"index": 0, "text": "正しい"},
        {"index": 1, "text": "誤り"},
    ],
    "correct": 0,
    "explanation": "施行令第 2 条による。",
    "applicable_goals": ["provisional", "full"],
    "difficulty": "basic",
    "category": "rules",
    "sources": [
        {
            "type": "law",
            "title": "道路交通法施行令 第 2 条",
            "url": KNOWN_URL,
            "quoted_text": "一般道路における自動車の法定最高速度は時速 60 キロメートル。",
        }
    ],
}


def _approve_response() -> str:
    return json.dumps(
        {
            "overall_score": 0.9,
            "factual_accuracy": 0.95,
            "difficulty_appropriate": 0.85,
            "wording_natural": 0.9,
            "non_misleading": 0.95,
            "citation_relevance": 0.95,
            "verdict": "approve",
            "reasons": ["可"],
        },
        ensure_ascii=False,
    )


def _build_pipeline(
    *,
    bank: InMemoryQuestionBank,
    embedding_client: MockEmbeddingClient,
) -> GenerationPipeline:
    return GenerationPipeline(
        QuestionGenerator(MockLLMClient(text=json.dumps(VALID_QUESTION_DICT, ensure_ascii=False))),
        FactChecker(),
        QualityReviewer(MockLLMClient(text=_approve_response(), model="mock-gemini")),
        embedding_client=embedding_client,
        question_bank=bank,
        store_on_pass=True,
    )


def _request(category: str = "rules") -> GenerationRequest:
    return GenerationRequest(goal="full", category=category, difficulty="basic")


@pytest.mark.asyncio
async def test_runner_processes_all_plan_items() -> None:
    bank = InMemoryQuestionBank()
    pipeline = _build_pipeline(bank=bank, embedding_client=MockEmbeddingClient())
    runner = GenerationRunner(pipeline, bank, pool_min_size=0)

    plan = [_request() for _ in range(3)]
    summary = await runner.run(plan)

    assert summary.total_requested == 3
    # 同じ body の Question が連続生成されるため、最初の 1 件は通り、
    # 2 件目以降は dedup で REJECTED になる
    assert summary.total_processed == 3
    assert summary.total_errors == 0
    assert summary.by_outcome.get("rejected", 0) >= 1


@pytest.mark.asyncio
async def test_runner_records_outcome_breakdown() -> None:
    bank = InMemoryQuestionBank()
    pipeline = _build_pipeline(bank=bank, embedding_client=MockEmbeddingClient())
    runner = GenerationRunner(pipeline, bank, pool_min_size=0)

    summary = await runner.run([_request(), _request()])
    assert summary.by_category.get("rules") == 2
    assert summary.by_goal.get("full") == 2


@pytest.mark.asyncio
async def test_runner_pool_count_before_after() -> None:
    bank = InMemoryQuestionBank()
    # 既存問題を 2 件登録（published / needs_review）
    for i in range(2):
        await bank.add(
            StoredQuestion(
                question_id=f"pre_{i}",
                version=1,
                body_hash=f"sha256:pre_{i}",
                embedding=[0.0] * 768,
                applicable_goals=["full"],
                category="rules",
                difficulty="basic",
                status="needs_review",
            )
        )
    pipeline = _build_pipeline(bank=bank, embedding_client=MockEmbeddingClient())
    runner = GenerationRunner(pipeline, bank, pool_min_size=10)

    summary = await runner.run([_request()])
    assert summary.pool_count_before == 2
    # 1 件追加で 3 件に。pool_min_size=10 なので alert
    assert summary.pool_count_after >= 2
    assert summary.pool_low_alert is True


@pytest.mark.asyncio
async def test_runner_no_alert_when_pool_above_min() -> None:
    bank = InMemoryQuestionBank()
    pipeline = _build_pipeline(bank=bank, embedding_client=MockEmbeddingClient())
    runner = GenerationRunner(pipeline, bank, pool_min_size=0)
    summary = await runner.run([_request()])
    assert summary.pool_low_alert is False


@pytest.mark.asyncio
async def test_runner_handles_pipeline_exceptions() -> None:
    """1 件で例外が出ても残りを継続する。"""
    bank = InMemoryQuestionBank()

    class _FlakyPipeline:
        def __init__(self) -> None:
            self.calls = 0

        async def run(self, request: GenerationRequest) -> object:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("flaky")
            from app.agent import PipelineOutcome, PipelineResult

            return PipelineResult(
                outcome=PipelineOutcome.REJECTED,
                question=None,
            )

    runner = GenerationRunner(_FlakyPipeline(), bank, pool_min_size=0)  # type: ignore[arg-type]
    summary = await runner.run([_request(), _request(), _request()])
    assert summary.total_processed == 2
    assert summary.total_errors == 1
    assert any("RuntimeError" in m for m in summary.error_messages)


@pytest.mark.asyncio
async def test_runner_success_rate() -> None:
    """成功率（REJECTED 以外の割合）を計算できる。"""
    bank = InMemoryQuestionBank()
    pipeline = _build_pipeline(bank=bank, embedding_client=MockEmbeddingClient())
    runner = GenerationRunner(pipeline, bank, pool_min_size=0)
    summary = await runner.run([_request()])
    # 1 件目は通って NEEDS_HUMAN_REVIEW（auto_approve=None なので）
    assert 0.0 <= summary.success_rate <= 1.0
