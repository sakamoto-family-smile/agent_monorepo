"""classify_intent (intent.py) のテスト。

MockLLMClient で出力を固定し、 parse 経路を deterministic に検証する。
"""

from __future__ import annotations

import pytest
from llm_client import MockLLMClient

from app.graph.agents.intent import IntentResult, classify_intent


class TestClassifyIntent:
    async def test_empty_query_is_out_of_scope(self) -> None:
        result = await classify_intent("", MockLLMClient(fixed_reply="ignored"))
        assert result == IntentResult(intent="out_of_scope", category=None, confidence=1.0)

    async def test_garbage_category_with_high_confidence(self) -> None:
        llm = MockLLMClient(fixed_reply='{"category":"garbage","confidence":0.95}')
        result = await classify_intent("ゴミの日いつ？", llm)
        assert result.intent == "rag"
        assert result.category == "garbage"
        assert result.confidence == 0.95

    async def test_low_confidence_drops_category_filter(self) -> None:
        llm = MockLLMClient(fixed_reply='{"category":"garbage","confidence":0.3}')
        result = await classify_intent("ゴミ？", llm)
        assert result.intent == "rag"
        assert result.category is None  # confidence < 0.5 で全体検索に fallback
        assert result.confidence == 0.3

    async def test_other_category_routes_to_out_of_scope(self) -> None:
        llm = MockLLMClient(fixed_reply='{"category":"other","confidence":0.8}')
        result = await classify_intent("こんにちは", llm)
        assert result.intent == "out_of_scope"
        assert result.category is None

    async def test_unparseable_output_falls_back_to_rag(self) -> None:
        llm = MockLLMClient(fixed_reply="これは JSON ではない")
        result = await classify_intent("質問", llm)
        assert result.intent == "rag"
        assert result.category is None
        assert result.confidence == 0.0

    async def test_invalid_category_falls_back_to_rag(self) -> None:
        llm = MockLLMClient(fixed_reply='{"category":"invented","confidence":0.9}')
        result = await classify_intent("質問", llm)
        assert result.intent == "rag"
        assert result.category is None

    async def test_json_with_surrounding_markdown(self) -> None:
        """LLM が ```json ... ``` のように装飾しても拾える。"""
        raw = "```json\n{\"category\":\"disaster\",\"confidence\":0.9}\n```"
        llm = MockLLMClient(fixed_reply=raw)
        result = await classify_intent("避難所どこ", llm)
        assert result.category == "disaster"
        assert result.confidence == 0.9

    async def test_llm_exception_falls_back_to_rag(self) -> None:
        class _RaisingLLM:
            async def complete(self, *, system: str, user: str, cache_system: bool = False) -> str:
                raise RuntimeError("vertex outage")

            async def complete_messages(
                self, *, system: str, messages: list, cache_system: bool = False
            ) -> str:
                raise RuntimeError("unused")

        result = await classify_intent("質問", _RaisingLLM())  # type: ignore[arg-type]
        assert result.intent == "rag"
        assert result.confidence == 0.0


@pytest.mark.parametrize(
    "category,expected",
    [
        ("disaster", "disaster"),
        ("parenting", "parenting"),
        ("garbage", "garbage"),
        ("procedure", "procedure"),
        ("tourism", "tourism"),
        ("cityhall", "cityhall"),
    ],
)
async def test_each_valid_category_passes_through(category: str, expected: str) -> None:
    llm = MockLLMClient(fixed_reply=f'{{"category":"{category}","confidence":0.9}}')
    result = await classify_intent("質問", llm)
    assert result.category == expected
    assert result.intent == "rag"
