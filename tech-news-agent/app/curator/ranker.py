"""ルールベース Ranker。

- final_score = llm_score * source_weight でソート
- トラック別 (news / arxiv) に Top N を抽出
- 閾値 `RELEVANCE_THRESHOLD` 未満は切り捨て (ただし arxiv は最低 1 本を配信する
  方針にするかは運用時判断。Phase 1 は閾値を適用して 0 本もあり得る)
"""

from __future__ import annotations

from datetime import UTC, datetime

from models import CuratedArticle, Digest


def rank(
    curated: list[CuratedArticle],
    *,
    top_news_n: int,
    top_arxiv_n: int,
    relevance_threshold: float,
) -> Digest:
    passing = [a for a in curated if a.final_score >= relevance_threshold]

    news = sorted(
        (a for a in passing if a.track == "news"),
        key=lambda a: a.final_score,
        reverse=True,
    )[:top_news_n]

    arxiv = sorted(
        (a for a in passing if a.track == "arxiv"),
        key=lambda a: a.final_score,
        reverse=True,
    )[:top_arxiv_n]

    return Digest(
        generated_at=datetime.now(UTC),
        top_news=news,
        top_arxiv=arxiv,
    )
