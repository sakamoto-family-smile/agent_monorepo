"""LLM バッチスコアリング (関連度 0-10 点)。

- 10 件まとめて 1 プロンプトで採点 (コスト 1/10)
- 失敗時 (parse error / LLM 例外) は 0 点 + reason="scoring_failed" で返す
  (pipeline 全体を止めない)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from curator.prompts import SCORER_SYSTEM
from llm_client import LLMClient
from models import RawArticle

logger = logging.getLogger(__name__)

BATCH_SIZE = 10


@dataclass(frozen=True)
class ScoringOutcome:
    score: float
    reason: str | None


def _build_batch_prompt(items: list[tuple[int, RawArticle]]) -> str:
    parts = ["以下の記事 (id, title, body_head) を JSON 配列で採点してください:\n"]
    for idx, art in items:
        body_head = (art.content or "")[:1000]
        parts.append(f"---\nid: {idx}\ntitle: {art.title}\nbody_head: {body_head}\n")
    parts.append(
        "\n出力: 必ず JSON 配列のみ。各要素は "
        '{"id": <idx>, "score": <0-10>, "reason": "<50字以内>"} 形式。'
    )
    return "\n".join(parts)


def _extract_json_array(text: str) -> list[dict]:
    """LLM 応答から JSON 配列を抽出。先頭の ```json ... ``` 等のノイズ除去。"""
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n", "", s)
        s = re.sub(r"\n```$", "", s).strip()
    # 最初の '[' から最後の ']' を切り出し (念のため)
    start = s.find("[")
    end = s.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON array in response")
    return json.loads(s[start : end + 1])


async def score_articles(
    llm: LLMClient,
    articles: list[RawArticle],
    *,
    batch_size: int = BATCH_SIZE,
) -> dict[str, ScoringOutcome]:
    """article_id → ScoringOutcome のマップを返す。"""
    results: dict[str, ScoringOutcome] = {}
    if not articles:
        return results

    # バッチ分割
    for i in range(0, len(articles), batch_size):
        batch = articles[i : i + batch_size]
        indexed = list(enumerate(batch))  # (idx within batch, article)
        user_prompt = _build_batch_prompt(indexed)
        try:
            raw = await llm.complete(
                system=SCORER_SYSTEM,
                user=user_prompt,
                cache_system=True,
            )
            parsed = _extract_json_array(raw)
        except Exception as exc:
            logger.warning(
                "scorer batch failed (batch %d/%d): %s",
                i // batch_size + 1,
                (len(articles) + batch_size - 1) // batch_size,
                exc,
            )
            # このバッチは全件 0 点で落とす
            for _, art in indexed:
                results[art.article_id] = ScoringOutcome(
                    score=0.0, reason="scoring_failed"
                )
            continue

        # index → article マップ
        idx_to_article = {idx: art for idx, art in indexed}
        seen: set[int] = set()
        for item in parsed:
            try:
                idx = int(item.get("id"))
                score = float(item.get("score"))
                reason = str(item.get("reason") or "")[:100]
                art = idx_to_article.get(idx)
                if art is None:
                    continue
                # 0〜10 にクリップ
                score = max(0.0, min(10.0, score))
                results[art.article_id] = ScoringOutcome(score=score, reason=reason)
                seen.add(idx)
            except (TypeError, ValueError):
                continue

        # parse したが応答に含まれなかった分は 0 点
        for idx, art in indexed:
            if idx not in seen:
                results[art.article_id] = ScoringOutcome(
                    score=0.0, reason="no_score_returned"
                )

    return results
