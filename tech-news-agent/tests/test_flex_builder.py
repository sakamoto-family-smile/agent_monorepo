"""Flex Message builder テスト。"""

from __future__ import annotations

from datetime import UTC, datetime

from models import CuratedArticle, Digest, RawArticle
from publisher.flex_builder import alt_text_for, build_digest_flex


def _curated(aid: str, *, track: str, title: str, summary: str) -> CuratedArticle:
    raw = RawArticle(
        article_id=aid,
        source_type="arxiv" if track == "arxiv" else "rss",
        source_name="src",
        url=f"https://x/{aid}",
        url_normalized=f"https://x/{aid}",
        title=title,
        content="",
        content_preview="",
        fetched_at=datetime.now(UTC),
    )
    return CuratedArticle(
        article_id=aid,
        raw=raw,
        llm_relevance_score=8.0,
        source_weight=1.5,
        final_score=12.0,
        summary_ja=summary,
        tags=["bigquery", "iceberg"],
        track=track,
    )


def test_carousel_bubbles_under_10():
    """10 本超の候補でも LINE API 上限の 10 bubble 以内に収まる。"""
    curated_news = [_curated(f"n{i}", track="news", title=f"T{i}", summary="S") for i in range(8)]
    curated_arxiv = [_curated(f"a{i}", track="arxiv", title=f"A{i}", summary="S") for i in range(3)]
    digest = Digest(
        generated_at=datetime(2026, 4, 24, 22, 0, tzinfo=UTC),
        top_news=curated_news,
        top_arxiv=curated_arxiv,
    )
    flex = build_digest_flex(digest)
    assert flex["type"] == "carousel"
    assert 1 <= len(flex["contents"]) <= 10


def test_header_bubble_is_first():
    digest = Digest(
        generated_at=datetime(2026, 4, 24, tzinfo=UTC),
        top_news=[_curated("n1", track="news", title="T", summary="S")],
        top_arxiv=[],
    )
    flex = build_digest_flex(digest)
    header = flex["contents"][0]
    # 先頭バブルは日付/ヘッダー
    text_contents = header["body"]["contents"]
    assert any("2026/04/24" in c.get("text", "") for c in text_contents)


def test_article_bubble_has_uri_action():
    digest = Digest(
        generated_at=datetime(2026, 4, 24, tzinfo=UTC),
        top_news=[_curated("n1", track="news", title="Title", summary="Summary")],
        top_arxiv=[],
    )
    flex = build_digest_flex(digest)
    article_bubble = flex["contents"][1]
    action = article_bubble["footer"]["contents"][0]["action"]
    assert action["type"] == "uri"
    assert action["uri"].startswith("https://")


def test_arxiv_bubble_uses_pdf_url_when_available():
    raw = RawArticle(
        article_id="a1",
        source_type="arxiv",
        source_name="arxiv",
        url="https://arxiv.org/abs/2501.12345",
        url_normalized="https://arxiv.org/abs/2501.12345",
        title="Paper",
        content="abstract",
        content_preview="abstract",
        fetched_at=datetime.now(UTC),
        arxiv_pdf_url="https://arxiv.org/pdf/2501.12345.pdf",
    )
    art = CuratedArticle(
        article_id="a1",
        raw=raw,
        llm_relevance_score=9.0,
        source_weight=1.0,
        final_score=9.0,
        summary_ja="要約",
        tags=["vector-search"],
        track="arxiv",
    )
    digest = Digest(
        generated_at=datetime.now(UTC), top_news=[], top_arxiv=[art]
    )
    flex = build_digest_flex(digest)
    article_bubble = flex["contents"][1]
    action = article_bubble["footer"]["contents"][0]["action"]
    assert action["uri"].endswith(".pdf")


def test_alt_text_includes_date_and_total():
    digest = Digest(
        generated_at=datetime(2026, 4, 24, tzinfo=UTC),
        top_news=[_curated(f"n{i}", track="news", title="T", summary="S") for i in range(3)],
        top_arxiv=[_curated("a1", track="arxiv", title="P", summary="S")],
    )
    assert "2026/04/24" in alt_text_for(digest)
    assert "Top 4" in alt_text_for(digest)
