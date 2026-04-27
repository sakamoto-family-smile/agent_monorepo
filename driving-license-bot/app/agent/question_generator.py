"""Question Generator agent。

LLM 呼び出し → JSON parse → Question スキーマ検証の 3 ステップ。Phase 2-B では
単一エージェント（Supervisor / 多段オーケストレーションは Phase 2-C 以降）。

retry 戦略:
- パースエラー / バリデーションエラーは最大 N 回（既定 1 回）リトライ
- LLMClient 自体のエラーはリトライせず即時 raise（Vertex 側のリトライに委ねる）
"""

from __future__ import annotations

import json
import logging
import re
import uuid

from pydantic import ValidationError

from app.agent.corpus import pick_snippets
from app.agent.errors import (
    GenerationParseError,
    GenerationValidationError,
)
from app.agent.llm_client import LLMClient
from app.agent.models import GenerationRequest, GenerationResult
from app.agent.prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
)
from app.config import settings
from app.models import Question

logger = logging.getLogger(__name__)


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json_text(raw: str) -> str:
    """LLM 出力から JSON 部分を抽出する。

    プロンプトで「JSON のみ」と指示しているが、念のため Markdown コードフェンス
    `​```json ... ​```` で囲まれたケースもサルベージする。
    """
    raw_stripped = raw.strip()
    if raw_stripped.startswith("{") and raw_stripped.endswith("}"):
        return raw_stripped
    match = _JSON_FENCE_RE.search(raw_stripped)
    if match:
        return match.group(1).strip()
    # fallback: 最初の { と最後の } の間
    first = raw_stripped.find("{")
    last = raw_stripped.rfind("}")
    if 0 <= first < last:
        return raw_stripped[first : last + 1]
    raise GenerationParseError("no JSON object found in LLM response", raw=raw)


def _ensure_unique_id(question_data: dict) -> dict:
    """LLM が `id` をサボったり重複させたりするのを防ぐため、生成側で一意 suffix を割当。"""
    qid = question_data.get("id") or "q_gen"
    suffix = uuid.uuid4().hex[:10]
    question_data["id"] = f"{qid}_{suffix}" if not qid.endswith(suffix) else qid
    return question_data


class QuestionGenerator:
    def __init__(self, llm: LLMClient, *, max_retries: int = 1) -> None:
        self._llm = llm
        self._max_retries = max(0, max_retries)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        snippets = pick_snippets(request.category)
        if not snippets:
            raise GenerationValidationError(
                f"no grounding corpus for category={request.category}"
            )
        user = build_user_prompt(
            goal=request.goal,
            category=request.category,
            difficulty=request.difficulty,
            snippets=snippets,
            topic_hint=request.topic_hint,
        )
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            response = self._llm.generate(
                system=SYSTEM_PROMPT,
                user=user,
                max_tokens=settings.agent_max_tokens,
                temperature=settings.agent_temperature,
                cache_system=True,
            )
            try:
                json_text = _extract_json_text(response.text)
                data = json.loads(json_text)
            except (json.JSONDecodeError, GenerationParseError) as exc:
                last_error = exc
                logger.warning(
                    "JSON parse failed (attempt %d/%d): %s",
                    attempt + 1,
                    self._max_retries + 1,
                    exc,
                )
                continue
            data = _ensure_unique_id(data)
            try:
                question = Question.model_validate(data)
            except ValidationError as exc:
                last_error = exc
                logger.warning(
                    "schema validation failed (attempt %d/%d): %s",
                    attempt + 1,
                    self._max_retries + 1,
                    exc,
                )
                continue
            return GenerationResult(
                question=question,
                model=response.model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cache_read_input_tokens=response.cache_read_input_tokens,
                cache_creation_input_tokens=response.cache_creation_input_tokens,
            )
        # 全 retry 失敗
        if isinstance(last_error, ValidationError):
            raise GenerationValidationError(
                "Question schema validation failed after retries",
                details=str(last_error),
            ) from last_error
        if isinstance(last_error, json.JSONDecodeError):
            raise GenerationParseError(
                "JSON decode failed after retries", raw=str(last_error)
            ) from last_error
        if isinstance(last_error, GenerationParseError):
            raise last_error
        raise GenerationParseError("generation failed for unknown reason")


__all__ = ["QuestionGenerator"]
