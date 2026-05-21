"""Intent 分類 sub-agent。

ユーザー発話 1 件 → `Intent` (rag / out_of_scope) + 検索 category。
LLM 出力 (JSON 1 行) を期待し、 parse 失敗時は fallback で `rag` + category None
にする (RAG 側の全体検索で何かしらヒットさせる救済策)。

settings の `rag_enabled=False` 時は LLM を呼ばずに out_of_scope 固定。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from llm_client import LLMClient

from app.graph.state import Intent
from app.skills import load_skill

logger = logging.getLogger(__name__)

_VALID_CATEGORIES = {
    "disaster",
    "parenting",
    "garbage",
    "procedure",
    "tourism",
    "cityhall",
    "other",
}
_OUT_OF_SCOPE_CATEGORIES = {"other"}
_MIN_CONFIDENCE = 0.5


@dataclass(frozen=True)
class IntentResult:
    """classify_intent の返却値。"""

    intent: Intent
    category: str | None
    confidence: float


async def classify_intent(query: str, llm: LLMClient) -> IntentResult:
    """発話を分類して Intent + category を決める。

    LLM 呼出が失敗した / JSON parse できない場合は、 conservative に
    `rag + category=None + confidence=0.0` を返す (RAG 側で全体検索される)。
    """
    if not query.strip():
        return IntentResult(intent="out_of_scope", category=None, confidence=1.0)

    skill = load_skill("category_routing")
    try:
        raw = await llm.complete(system=skill, user=query)
    except Exception:  # noqa: BLE001 — LLM ベンダ依存例外を握って fallback
        logger.exception("classify_intent: LLM call failed, falling back to rag")
        return IntentResult(intent="rag", category=None, confidence=0.0)

    parsed = _parse_intent_json(raw)
    if parsed is None:
        logger.warning("classify_intent: could not parse LLM output: %r", raw[:200])
        return IntentResult(intent="rag", category=None, confidence=0.0)

    category, confidence = parsed
    if category not in _VALID_CATEGORIES:
        return IntentResult(intent="rag", category=None, confidence=0.0)

    if category in _OUT_OF_SCOPE_CATEGORIES and confidence >= _MIN_CONFIDENCE:
        return IntentResult(intent="out_of_scope", category=None, confidence=confidence)

    # confidence が低ければ category フィルタを使わず全体検索する
    effective_category = category if confidence >= _MIN_CONFIDENCE else None
    return IntentResult(
        intent="rag",
        category=effective_category,
        confidence=confidence,
    )


def _parse_intent_json(raw: str) -> tuple[str, float] | None:
    """LLM 出力から最初の JSON object 1 個を取り出して (category, confidence) を返す。"""
    # マーカー (```json ... ```) や前置きを含むケースを救済
    match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    category = obj.get("category")
    confidence = obj.get("confidence")
    if not isinstance(category, str):
        return None
    if not isinstance(confidence, (int, float)):
        return None
    return category, float(confidence)


__all__ = ["IntentResult", "classify_intent"]
