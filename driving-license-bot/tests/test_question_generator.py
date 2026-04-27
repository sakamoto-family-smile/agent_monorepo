"""Question Generator のユニットテスト（Mock LLM）。"""

from __future__ import annotations

import json

import pytest

from app.agent import (
    GenerationParseError,
    GenerationRequest,
    GenerationValidationError,
    MockLLMClient,
    QuestionGenerator,
)
from app.agent.corpus import pick_snippets
from app.agent.llm_client import LLMResponse
from app.agent.question_generator import _ensure_unique_id, _extract_json_text

# ---- helpers ----

VALID_QUESTION_DICT = {
    "id": "q_gen_sample",
    "version": 1,
    "body": "信号機の青色の灯火は、自動車が直進・左折・右折いずれもできることを示している。",
    "format": "true_false",
    "choices": [
        {"index": 0, "text": "正しい"},
        {"index": 1, "text": "誤り"},
    ],
    "correct": 0,
    "explanation": (
        "結論: 正しい。道路交通法施行令第 2 条により青色の灯火は直進・左折・右折"
        "が可能。覚え方: 二段階右折を要する原付は例外。"
    ),
    "applicable_goals": ["provisional", "full"],
    "difficulty": "basic",
    "category": "rules",
    "sources": [
        {
            "type": "law",
            "title": "道路交通法施行令 第 2 条",
            "url": "https://laws.e-gov.go.jp/document?lawid=335CO0000000270",
            "quoted_text": "青色の灯火: 自動車は直進、左折、右折することができる。",
        }
    ],
}


def _request() -> GenerationRequest:
    return GenerationRequest(goal="full", category="rules", difficulty="basic")


# ---- _extract_json_text の単体 ----

def test_extract_json_text_plain() -> None:
    raw = '   {"a": 1}\n  '
    assert _extract_json_text(raw) == '{"a": 1}'


def test_extract_json_text_code_fence() -> None:
    raw = '前置き\n```json\n{"x": 2}\n```\n後ろ'
    assert _extract_json_text(raw) == '{"x": 2}'


def test_extract_json_text_fallback_to_braces() -> None:
    raw = '解説: 以下を返します。\n{"y": 3}\nこれが回答です。'
    assert _extract_json_text(raw) == '{"y": 3}'


def test_extract_json_text_raises_when_no_brace() -> None:
    with pytest.raises(GenerationParseError):
        _extract_json_text("nothing here")


def test_ensure_unique_id_appends_suffix() -> None:
    out = _ensure_unique_id({"id": "q_gen"})
    assert out["id"].startswith("q_gen_")
    assert len(out["id"]) > len("q_gen_")


# ---- generator 本体 ----

def test_generate_returns_validated_question() -> None:
    mock = MockLLMClient(text=json.dumps(VALID_QUESTION_DICT, ensure_ascii=False))
    generator = QuestionGenerator(mock)
    result = generator.generate(_request())

    assert result.question.body.startswith("信号機")
    assert result.question.applicable_goals == ["provisional", "full"]
    assert result.question.sources, "sources must be non-empty"
    assert result.model == "mock-claude"
    assert result.input_tokens >= 0
    # LLM 呼び出しは 1 回のみ
    assert len(mock.calls) == 1
    # system プロンプトが渡っており cache_system=True
    assert mock.calls[0]["cache_system"] is True
    assert "学科試験" in mock.calls[0]["system"]


def test_generate_retries_on_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """1 回目: ゴミ、2 回目: 正しい JSON を返すようにし、retry が効くことを検証。"""
    responses = iter(
        [
            LLMResponse(text="this is not json at all", model="mock-claude"),
            LLMResponse(
                text=json.dumps(VALID_QUESTION_DICT, ensure_ascii=False),
                model="mock-claude",
            ),
        ]
    )

    class _StubLLM:
        def generate(self, **kwargs: object) -> LLMResponse:
            return next(responses)

    generator = QuestionGenerator(_StubLLM(), max_retries=1)
    result = generator.generate(_request())
    assert result.question.id.startswith(VALID_QUESTION_DICT["id"])


def test_generate_raises_on_validation_failure() -> None:
    """sources が空 → Question schema 違反 → retry 上限超で raise。"""
    bad = {**VALID_QUESTION_DICT, "sources": []}
    mock = MockLLMClient(text=json.dumps(bad, ensure_ascii=False))
    generator = QuestionGenerator(mock, max_retries=1)
    with pytest.raises(GenerationValidationError):
        generator.generate(_request())


def test_generate_raises_on_parse_failure_after_retries() -> None:
    mock = MockLLMClient(text="completely garbage text without braces")
    generator = QuestionGenerator(mock, max_retries=1)
    with pytest.raises(GenerationParseError):
        generator.generate(_request())


def test_generate_id_is_unique_across_calls() -> None:
    mock = MockLLMClient(text=json.dumps(VALID_QUESTION_DICT, ensure_ascii=False))
    generator = QuestionGenerator(mock)
    r1 = generator.generate(_request())
    r2 = generator.generate(_request())
    assert r1.question.id != r2.question.id


def test_user_prompt_includes_grounding_urls() -> None:
    """grounding URL が user prompt に含まれること（LLM への明示）。"""
    mock = MockLLMClient(text=json.dumps(VALID_QUESTION_DICT, ensure_ascii=False))
    generator = QuestionGenerator(mock)
    generator.generate(_request())
    user_prompt = mock.calls[0]["user"]
    snippets = pick_snippets("rules")
    for s in snippets:
        assert s.url in user_prompt, f"grounding URL {s.url} missing from user prompt"


def test_corpus_returns_fallback_for_unknown_category() -> None:
    """未定義カテゴリでは rules を fallback として返す。"""
    snippets = pick_snippets("nonexistent")
    assert snippets, "fallback to rules should not be empty"


def test_build_llm_client_with_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """AGENT_LLM_MOCK=true で MockLLMClient が返ること。"""
    from importlib import reload

    import app.config as config_module

    monkeypatch.setenv("AGENT_LLM_MOCK", "true")
    reload(config_module)
    from app.agent.llm_client import MockLLMClient as _Mock
    from app.agent.llm_client import build_llm_client

    client = build_llm_client()
    assert isinstance(client, _Mock)


def test_build_llm_client_requires_project(monkeypatch: pytest.MonkeyPatch) -> None:
    from importlib import reload

    import app.config as config_module

    monkeypatch.setenv("AGENT_LLM_MOCK", "false")
    monkeypatch.setenv("ANTHROPIC_VERTEX_PROJECT_ID", "")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "")
    reload(config_module)
    from app.agent.llm_client import LLMClientError, build_llm_client

    with pytest.raises(LLMClientError, match="VERTEX_PROJECT_ID"):
        build_llm_client()
