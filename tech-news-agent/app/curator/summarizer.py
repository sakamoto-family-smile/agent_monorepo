"""LLM による日本語要約生成 (1 記事 1 プロンプト)。"""

from __future__ import annotations

import json
import logging
import re

from curator.prompts import SUMMARIZER_SYSTEM
from llm_client import LLMClient
from models import RawArticle

logger = logging.getLogger(__name__)


def _build_prompt(article: RawArticle) -> str:
    body = (article.content or "")[:2000]
    return (
        f"記事タイトル: {article.title}\n"
        f"ソース: {article.source_name} ({article.source_type})\n"
        f"本文:\n{body}\n"
    )


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


async def summarize_article(llm: LLMClient, article: RawArticle) -> str:
    """1 記事の日本語要約を返す。失敗時はタイトルを fallback として返す。"""
    user_prompt = _build_prompt(article)
    try:
        raw = await llm.complete(
            system=SUMMARIZER_SYSTEM,
            user=user_prompt,
            cache_system=True,
        )
        parsed = _extract_json_object(raw)
        summary = str(parsed.get("summary_ja") or "").strip()
        if not summary:
            raise ValueError("empty summary_ja")
        # LINE 配信カード向けに 150 字で切る
        if len(summary) > 150:
            summary = summary[:149] + "…"
        return summary
    except Exception as exc:
        logger.warning("summarizer failed article_id=%s error=%s", article.article_id, exc)
        # fallback: タイトルをそのまま要約として使う
        return article.title[:150]
