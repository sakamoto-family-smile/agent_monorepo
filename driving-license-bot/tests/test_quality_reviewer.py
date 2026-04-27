"""Quality Reviewer のユニットテスト（Mock LLM）。"""

from __future__ import annotations

import json

import pytest

from app.agent import GenerationParseError, MockLLMClient, QualityReviewer
from app.models import Question, QuestionFormat


def _question() -> Question:
    return Question(
        id="q_review_001",
        body="信号機の青色の灯火は直進・左折・右折いずれもできることを示している。",
        format=QuestionFormat.TRUE_FALSE,
        choices=[
            {"index": 0, "text": "正しい"},
            {"index": 1, "text": "誤り"},
        ],
        correct=0,
        explanation="施行令第 2 条に基づく。",
        applicable_goals=["provisional", "full"],
        sources=[
            {
                "type": "law",
                "title": "施行令第 2 条",
                "url": "https://laws.e-gov.go.jp/document?lawid=335CO0000000270",
                "quoted_text": "青色の灯火 — 直進・左折・右折ができる。",
            }
        ],
    )


def _ok_response() -> dict:
    return {
        "overall_score": 0.85,
        "factual_accuracy": 0.9,
        "difficulty_appropriate": 0.8,
        "wording_natural": 0.85,
        "non_misleading": 0.9,
        "citation_relevance": 0.95,
        "verdict": "approve",
        "reasons": ["事実関係正しい", "引用妥当"],
    }


def test_review_parses_valid_response() -> None:
    mock = MockLLMClient(text=json.dumps(_ok_response(), ensure_ascii=False))
    result = QualityReviewer(mock).review(_question())
    assert result.verdict == "approve"
    assert result.overall_score == 0.85
    assert "事実関係正しい" in result.reasons


def test_review_clamps_out_of_range_scores() -> None:
    bad = {**_ok_response(), "overall_score": 1.5, "factual_accuracy": -0.3}
    mock = MockLLMClient(text=json.dumps(bad, ensure_ascii=False))
    result = QualityReviewer(mock).review(_question())
    assert result.overall_score == 1.0
    assert result.factual_accuracy == 0.0


def test_review_rejects_invalid_verdict() -> None:
    bad = {**_ok_response(), "verdict": "totally_invalid"}
    mock = MockLLMClient(text=json.dumps(bad, ensure_ascii=False))
    with pytest.raises(GenerationParseError):
        QualityReviewer(mock, max_retries=0).review(_question())


def test_review_rejects_missing_keys() -> None:
    bad = {k: v for k, v in _ok_response().items() if k != "factual_accuracy"}
    mock = MockLLMClient(text=json.dumps(bad, ensure_ascii=False))
    with pytest.raises(GenerationParseError):
        QualityReviewer(mock, max_retries=0).review(_question())


def test_review_retries_on_garbage_response() -> None:
    """1 回目: ゴミ、2 回目: 正常で成功する。"""
    from app.agent.llm_client import LLMResponse

    responses = iter(
        [
            LLMResponse(text="not json", model="mock-gemini"),
            LLMResponse(
                text=json.dumps(_ok_response(), ensure_ascii=False),
                model="mock-gemini",
            ),
        ]
    )

    class _Stub:
        def generate(self, **kw: object) -> LLMResponse:
            return next(responses)

    result = QualityReviewer(_Stub(), max_retries=1).review(_question())
    assert result.verdict == "approve"


def test_review_handles_string_reasons_field() -> None:
    """reasons が list でなく単一文字列で来た場合も拾う。"""
    weird = {**_ok_response(), "reasons": "just one reason as string"}
    mock = MockLLMClient(text=json.dumps(weird, ensure_ascii=False))
    result = QualityReviewer(mock).review(_question())
    assert result.reasons == ["just one reason as string"]


def test_review_truncates_excessive_reasons() -> None:
    """reasons は最大 5 件に切り詰める。"""
    too_many = {**_ok_response(), "reasons": [f"r{i}" for i in range(20)]}
    mock = MockLLMClient(text=json.dumps(too_many, ensure_ascii=False))
    result = QualityReviewer(mock).review(_question())
    assert len(result.reasons) == 5
