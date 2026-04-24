"""Ranker のテスト。"""

from __future__ import annotations

from datetime import UTC, datetime

from curator.ranker import rank
from models import CuratedArticle, RawArticle


def _mk(aid: str, score: float, weight: float, track: str, source: str = "s") -> CuratedArticle:
    raw = RawArticle(
        article_id=aid,
        source_type="arxiv" if track == "arxiv" else "rss",
        source_name=source,
        url=f"https://x/{aid}",
        url_normalized=f"https://x/{aid}",
        title=f"title {aid}",
        content="body",
        content_preview="body",
        fetched_at=datetime.now(UTC),
    )
    return CuratedArticle(
        article_id=aid,
        raw=raw,
        llm_relevance_score=score,
        source_weight=weight,
        final_score=score * weight,
        summary_ja=f"summary {aid}",
        tags=[],
        track=track,
    )


def test_top_n_applied_per_track():
    curated = [
        _mk("n1", 9.0, 1.5, "news"),
        _mk("n2", 8.0, 1.5, "news"),
        _mk("n3", 7.0, 1.5, "news"),
        _mk("n4", 6.0, 1.5, "news"),
        _mk("a1", 9.0, 1.5, "arxiv"),
        _mk("a2", 8.0, 1.5, "arxiv"),
        _mk("a3", 7.0, 1.5, "arxiv"),
    ]
    digest = rank(curated, top_news_n=2, top_arxiv_n=1, relevance_threshold=5.0)
    assert [c.article_id for c in digest.top_news] == ["n1", "n2"]
    assert [c.article_id for c in digest.top_arxiv] == ["a1"]


def test_threshold_filters_out_below():
    curated = [
        _mk("a", 5.0, 1.0, "news"),   # final=5.0 通過
        _mk("b", 4.9, 1.0, "news"),   # final=4.9 不通過
        _mk("c", 10.0, 0.7, "news"),  # final=7.0 通過
    ]
    digest = rank(curated, top_news_n=10, top_arxiv_n=10, relevance_threshold=5.0)
    ids = [c.article_id for c in digest.top_news]
    assert "b" not in ids
    assert "a" in ids and "c" in ids


def test_source_weight_affects_order():
    # 生スコアは同じでも weight が高い方が上位に来る
    curated = [
        _mk("big_brand", 7.0, 1.5, "news", source="google_cloud"),
        _mk("small_blog", 7.0, 0.7, "news", source="reddit"),
    ]
    digest = rank(curated, top_news_n=10, top_arxiv_n=0, relevance_threshold=0.0)
    assert digest.top_news[0].article_id == "big_brand"


def test_empty_input_returns_empty_digest():
    digest = rank([], top_news_n=5, top_arxiv_n=2, relevance_threshold=5.0)
    assert digest.top_news == []
    assert digest.top_arxiv == []


def test_all_below_threshold_returns_empty():
    curated = [_mk("x", 1.0, 1.0, "news")]
    digest = rank(curated, top_news_n=5, top_arxiv_n=2, relevance_threshold=5.0)
    assert digest.top_news == []
