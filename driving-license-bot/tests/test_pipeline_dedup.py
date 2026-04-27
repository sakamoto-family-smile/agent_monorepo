"""GenerationPipeline の dedup ステップに焦点を当てたテスト。"""

from __future__ import annotations

import json

import pytest

from app.agent import (
    FactChecker,
    GenerationPipeline,
    GenerationRequest,
    MockEmbeddingClient,
    MockLLMClient,
    PipelineOutcome,
    QualityReviewer,
    QuestionGenerator,
)
from app.repositories.question_bank import (
    InMemoryQuestionBank,
    StoredQuestion,
)

KNOWN_URL = "https://laws.e-gov.go.jp/document?lawid=335CO0000000270"

VALID_QUESTION_DICT = {
    "id": "q_dedup_sample",
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
    embedding_dim: int = 768,
    dedup_threshold: float = 0.92,
    store_on_pass: bool = False,
) -> GenerationPipeline:
    gen_llm = MockLLMClient(
        text=json.dumps(VALID_QUESTION_DICT, ensure_ascii=False),
        model="mock-claude",
    )
    review_llm = MockLLMClient(text=_approve_response(), model="mock-gemini")
    return GenerationPipeline(
        QuestionGenerator(gen_llm),
        FactChecker(),
        QualityReviewer(review_llm),
        embedding_client=MockEmbeddingClient(dimension=embedding_dim),
        question_bank=bank,
        dedup_threshold=dedup_threshold,
        store_on_pass=store_on_pass,
    )


def _request() -> GenerationRequest:
    return GenerationRequest(goal="full", category="rules", difficulty="basic")


@pytest.mark.asyncio
async def test_empty_bank_passes_dedup() -> None:
    bank = InMemoryQuestionBank()
    pipeline = _build_pipeline(bank=bank)
    result = await pipeline.run(_request())
    assert result.outcome == PipelineOutcome.NEEDS_HUMAN_REVIEW
    assert result.dedup is not None
    assert result.dedup.is_duplicate is False
    assert result.dedup.top_hits == []


@pytest.mark.asyncio
async def test_duplicate_question_rejected_short_circuits_review() -> None:
    """同じ body のテキストを既存問題として登録 → dedup で reject、reviewer は呼ばれない。"""
    bank = InMemoryQuestionBank()
    embedding_client = MockEmbeddingClient(dimension=768)
    # MockEmbedding は決定的なので、生成される body と同じ文を pre-populate
    same_body = VALID_QUESTION_DICT["body"]
    pre_embedding = embedding_client.embed(same_body)
    await bank.add(
        StoredQuestion(
            question_id="q_existing",
            version=1,
            body_hash="sha256:existing",
            embedding=pre_embedding,
            applicable_goals=["full"],
            category="rules",
            difficulty="basic",
        )
    )

    review_llm = MockLLMClient(text=_approve_response(), model="mock-gemini")
    gen_llm = MockLLMClient(
        text=json.dumps(VALID_QUESTION_DICT, ensure_ascii=False),
        model="mock-claude",
    )
    pipeline = GenerationPipeline(
        QuestionGenerator(gen_llm),
        FactChecker(),
        QualityReviewer(review_llm),
        embedding_client=embedding_client,
        question_bank=bank,
        dedup_threshold=0.92,
    )
    result = await pipeline.run(_request())

    assert result.outcome == PipelineOutcome.REJECTED
    assert result.dedup is not None
    assert result.dedup.is_duplicate is True
    assert result.dedup.top_hits[0].stored.question_id == "q_existing"
    assert any("[dedup]" in r for r in result.rejection_reasons)
    # reviewer は呼ばれていない（short-circuit）
    assert review_llm.calls == []
    assert result.quality_review is None


@pytest.mark.asyncio
async def test_dedup_threshold_can_be_loose() -> None:
    """しきい値を超えなければ duplicate 扱いされない。"""
    bank = InMemoryQuestionBank()
    # 同じ body を pre-populate（cosine ≈ 1.0）
    embedding_client = MockEmbeddingClient(dimension=768)
    pre_embedding = embedding_client.embed(VALID_QUESTION_DICT["body"])
    await bank.add(
        StoredQuestion(
            question_id="q_existing",
            version=1,
            body_hash="sha256:existing",
            embedding=pre_embedding,
            applicable_goals=["full"],
            category="rules",
            difficulty="basic",
        )
    )

    pipeline = _build_pipeline(bank=bank, dedup_threshold=1.5)  # 不可能なしきい値
    result = await pipeline.run(_request())
    # しきい値を超える hit がないので NEEDS_HUMAN_REVIEW に進む
    assert result.outcome == PipelineOutcome.NEEDS_HUMAN_REVIEW
    assert result.dedup is not None
    assert result.dedup.is_duplicate is False


@pytest.mark.asyncio
async def test_dedup_filters_by_category() -> None:
    """異なるカテゴリの類似問題は dedup でヒットしない。"""
    bank = InMemoryQuestionBank()
    embedding_client = MockEmbeddingClient(dimension=768)
    pre_embedding = embedding_client.embed(VALID_QUESTION_DICT["body"])
    # 同じ body だが category が違うため、find_similar(category="rules") では除外される
    await bank.add(
        StoredQuestion(
            question_id="q_signs",
            version=1,
            body_hash="sha256:signs",
            embedding=pre_embedding,
            applicable_goals=["full"],
            category="signs",  # ← 違うカテゴリ
            difficulty="basic",
        )
    )

    pipeline = _build_pipeline(bank=bank)
    result = await pipeline.run(_request())  # category=rules で問い合わせ
    assert result.outcome == PipelineOutcome.NEEDS_HUMAN_REVIEW
    assert result.dedup is not None
    assert result.dedup.is_duplicate is False


@pytest.mark.asyncio
async def test_pipeline_without_embedding_skips_dedup() -> None:
    """embedding_client / question_bank 未指定 → dedup ステップ全体をスキップ。"""
    gen_llm = MockLLMClient(
        text=json.dumps(VALID_QUESTION_DICT, ensure_ascii=False),
        model="mock-claude",
    )
    review_llm = MockLLMClient(text=_approve_response(), model="mock-gemini")
    pipeline = GenerationPipeline(
        QuestionGenerator(gen_llm),
        FactChecker(),
        QualityReviewer(review_llm),
        # embedding_client / question_bank を渡さない
    )
    result = await pipeline.run(_request())
    assert result.outcome == PipelineOutcome.NEEDS_HUMAN_REVIEW
    assert result.dedup is None  # スキップされた


@pytest.mark.asyncio
async def test_store_on_pass_writes_to_bank() -> None:
    bank = InMemoryQuestionBank()
    pipeline = _build_pipeline(bank=bank, store_on_pass=True)
    result = await pipeline.run(_request())
    assert result.outcome == PipelineOutcome.NEEDS_HUMAN_REVIEW
    # bank に書き込まれた
    assert await bank.count() == 1
    assert result.question is not None
    stored = await bank.get(result.question.id)
    assert stored is not None
    assert stored.status == "needs_review"


@pytest.mark.asyncio
async def test_store_on_pass_skipped_for_rejected() -> None:
    """duplicate で rejected なら bank に書かれない。"""
    bank = InMemoryQuestionBank()
    embedding_client = MockEmbeddingClient(dimension=768)
    pre_embedding = embedding_client.embed(VALID_QUESTION_DICT["body"])
    await bank.add(
        StoredQuestion(
            question_id="q_existing",
            version=1,
            body_hash="sha256:existing",
            embedding=pre_embedding,
            applicable_goals=["full"],
            category="rules",
            difficulty="basic",
        )
    )

    review_llm = MockLLMClient(text=_approve_response(), model="mock-gemini")
    gen_llm = MockLLMClient(
        text=json.dumps(VALID_QUESTION_DICT, ensure_ascii=False),
        model="mock-claude",
    )
    pipeline = GenerationPipeline(
        QuestionGenerator(gen_llm),
        FactChecker(),
        QualityReviewer(review_llm),
        embedding_client=embedding_client,
        question_bank=bank,
        store_on_pass=True,
    )
    await pipeline.run(_request())
    # 既存 1 件のまま、新規問題は登録されない
    assert await bank.count() == 1
