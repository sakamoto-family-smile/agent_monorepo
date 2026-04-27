"""GenerationPipeline の統合テスト（モック LLM）。"""

from __future__ import annotations

import json

import pytest

from app.agent import (
    FactChecker,
    GenerationPipeline,
    GenerationRequest,
    MockLLMClient,
    PipelineOutcome,
    QualityReviewer,
    QuestionGenerator,
)

# 実 corpus に存在する URL（fact checker を通過させるため）
KNOWN_URL = "https://laws.e-gov.go.jp/document?lawid=335CO0000000270"

VALID_QUESTION_DICT = {
    "id": "q_pipe_sample",
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


HALLUCINATED_QUESTION_DICT = {
    **VALID_QUESTION_DICT,
    "id": "q_pipe_bad",
    "sources": [
        {
            "type": "law",
            "title": "架空法令",
            "url": "https://example.com/non-existent",  # corpus 外
            "quoted_text": "この条文は実在しない",
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
            "reasons": ["事実関係正しい"],
        },
        ensure_ascii=False,
    )


def _reject_response() -> str:
    return json.dumps(
        {
            "overall_score": 0.3,
            "factual_accuracy": 0.2,
            "difficulty_appropriate": 0.5,
            "wording_natural": 0.6,
            "non_misleading": 0.4,
            "citation_relevance": 0.3,
            "verdict": "reject",
            "reasons": ["事実関係に誤り", "引用が無関係"],
        },
        ensure_ascii=False,
    )


def _build_pipeline(
    *, gen_text: str, review_text: str, auto_threshold: float | None = None
) -> GenerationPipeline:
    gen_llm = MockLLMClient(text=gen_text, model="mock-claude")
    review_llm = MockLLMClient(text=review_text, model="mock-gemini")
    return GenerationPipeline(
        QuestionGenerator(gen_llm),
        FactChecker(),
        QualityReviewer(review_llm),
        auto_approve_overall_score=auto_threshold,
    )


def _request() -> GenerationRequest:
    return GenerationRequest(goal="full", category="rules", difficulty="basic")


# ---- 各シナリオ ----

@pytest.mark.asyncio
async def test_happy_path_defaults_to_needs_human_review() -> None:
    """fact OK + reviewer approve でも、auto_threshold None なので人間レビュー必須。"""
    pipeline = _build_pipeline(
        gen_text=json.dumps(VALID_QUESTION_DICT, ensure_ascii=False),
        review_text=_approve_response(),
    )
    result = await pipeline.run(_request())
    assert result.outcome == PipelineOutcome.NEEDS_HUMAN_REVIEW
    assert result.passed_all
    assert result.fact_check is not None and result.fact_check.passed
    assert result.quality_review is not None
    assert result.quality_review.verdict == "approve"
    assert not result.rejection_reasons


@pytest.mark.asyncio
async def test_auto_approve_when_threshold_met() -> None:
    pipeline = _build_pipeline(
        gen_text=json.dumps(VALID_QUESTION_DICT, ensure_ascii=False),
        review_text=_approve_response(),
        auto_threshold=0.85,
    )
    result = await pipeline.run(_request())
    assert result.outcome == PipelineOutcome.APPROVED


@pytest.mark.asyncio
async def test_fact_check_fail_short_circuits_review() -> None:
    """corpus 外の URL → fact check fail → reviewer は呼ばれずに即 reject。"""
    review_llm = MockLLMClient(text=_approve_response(), model="mock-gemini")
    gen_llm = MockLLMClient(
        text=json.dumps(HALLUCINATED_QUESTION_DICT, ensure_ascii=False),
        model="mock-claude",
    )
    pipeline = GenerationPipeline(
        QuestionGenerator(gen_llm),
        FactChecker(),
        QualityReviewer(review_llm),
    )
    result = await pipeline.run(_request())
    assert result.outcome == PipelineOutcome.REJECTED
    assert any("url_not_in_corpus" in r for r in result.rejection_reasons)
    # reviewer は呼ばれていない
    assert review_llm.calls == []
    assert result.quality_review is None


@pytest.mark.asyncio
async def test_quality_reviewer_reject_marks_rejected() -> None:
    pipeline = _build_pipeline(
        gen_text=json.dumps(VALID_QUESTION_DICT, ensure_ascii=False),
        review_text=_reject_response(),
    )
    result = await pipeline.run(_request())
    assert result.outcome == PipelineOutcome.REJECTED
    assert result.fact_check is not None and result.fact_check.passed
    assert result.quality_review is not None
    assert result.quality_review.verdict == "reject"
    assert any("[review] reject" in r for r in result.rejection_reasons)


@pytest.mark.asyncio
async def test_below_threshold_falls_to_human_review() -> None:
    """approve verdict だが overall_score がしきい値未満 → 人間レビュー。"""
    weak = json.dumps(
        {
            "overall_score": 0.6,
            "factual_accuracy": 0.7,
            "difficulty_appropriate": 0.6,
            "wording_natural": 0.6,
            "non_misleading": 0.6,
            "citation_relevance": 0.6,
            "verdict": "approve",
            "reasons": ["可"],
        },
        ensure_ascii=False,
    )
    pipeline = _build_pipeline(
        gen_text=json.dumps(VALID_QUESTION_DICT, ensure_ascii=False),
        review_text=weak,
        auto_threshold=0.85,
    )
    result = await pipeline.run(_request())
    assert result.outcome == PipelineOutcome.NEEDS_HUMAN_REVIEW


@pytest.mark.asyncio
async def test_generator_failure_propagates() -> None:
    """Generator が失敗（パース不能）したら例外がそのまま伝播する。"""
    pipeline = _build_pipeline(
        gen_text="not json at all",
        review_text=_approve_response(),
    )
    with pytest.raises(Exception):  # GenerationParseError
        await pipeline.run(_request())
