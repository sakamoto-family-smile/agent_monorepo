"""LLM によるタグ付け (ドメインは Phase 1 では sources.yaml の domain を流用)。"""

from __future__ import annotations

import json
import logging
import re

from curator.prompts import TAGGER_SYSTEM
from llm_client import LLMClient
from models import RawArticle

logger = logging.getLogger(__name__)

MAX_TAGS = 5


def _sanitize_tag(tag: str) -> str | None:
    t = tag.strip().lower()
    # ハイフン / 英数のみ許可 (それ以外の記号は除く)
    t = re.sub(r"[^a-z0-9-]", "", t)
    if not t or len(t) > 30:
        return None
    return t


def _extract_json_object(text: str) -> dict:
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n", "", s)
        s = re.sub(r"\n```$", "", s).strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object in response")
    return json.loads(s[start : end + 1])


async def tag_article(
    llm: LLMClient,
    article: RawArticle,
    summary_ja: str,
) -> list[str]:
    """記事のタグを返す。失敗時は空リスト。"""
    user_prompt = (
        f"記事タイトル: {article.title}\n要約: {summary_ja}\nソース: {article.source_name}\n"
    )
    try:
        raw = await llm.complete(
            system=TAGGER_SYSTEM,
            user=user_prompt,
            cache_system=True,
        )
        parsed = _extract_json_object(raw)
    except Exception as exc:
        logger.warning("tagger failed article_id=%s error=%s", article.article_id, exc)
        return []

    tags_raw = parsed.get("tags") or []
    if not isinstance(tags_raw, list):
        return []
    clean: list[str] = []
    seen: set[str] = set()
    for t in tags_raw[: MAX_TAGS * 2]:  # 超過の安全余裕
        if not isinstance(t, str):
            continue
        s = _sanitize_tag(t)
        if s and s not in seen:
            clean.append(s)
            seen.add(s)
        if len(clean) >= MAX_TAGS:
            break
    return clean
