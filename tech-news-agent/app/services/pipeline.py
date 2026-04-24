"""Phase 1 MVP パイプライン。

  sources → Collect → Dedup → Score → Filter → Summarize+Tag → Rank → Publish

設計ポイント:
  - 各段階で analytics-platform に `business_event` を emit
  - 1 ソース失敗でパイプライン全体を止めない (collector 側で try/except 済)
  - LLM 呼び出し失敗は個別 article を 0 点扱い → 結果的に閾値未達で落ちる
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from collectors import arxiv_source, rss
from curator import ranker, scorer, summarizer, tagger
from instrumentation import get_analytics_logger
from llm_client import LLMClient
from models import CuratedArticle, Digest, RawArticle
from publisher.flex_builder import alt_text_for, build_digest_flex
from publisher.line_client import LinePublisherClient
from repositories.dedup_repo import DedupRepo
from services.source_config import SourcesConfig

from config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineResult:
    digest_id: str
    status: str                          # 'sent' | 'failed' | 'empty'
    collected_count: int
    new_count: int
    scored_count: int
    passing_count: int
    news_count: int
    arxiv_count: int
    line_success: int
    line_failure: int


def _emit(al, *, action: str, attributes: dict, severity: str = "INFO") -> None:
    try:
        al.emit(
            event_type="business_event",
            event_version="1.0.0",
            severity=severity,
            fields={
                "business_domain": "tech_news",
                "action": action,
                "resource_type": attributes.get("_resource_type", "pipeline"),
                "resource_id": attributes.get("_resource_id", ""),
                "attributes": {k: v for k, v in attributes.items() if not k.startswith("_")},
            },
        )
    except Exception:
        logger.exception("emit business_event action=%s failed (non-fatal)", action)


async def _collect(sources: SourcesConfig) -> list[RawArticle]:
    rss_articles = await rss.fetch_all(list(sources.rss))
    arxiv_articles = await arxiv_source.fetch_all(list(sources.arxiv))
    all_articles = rss_articles + arxiv_articles
    logger.info(
        "collected: rss=%d arxiv=%d total=%d",
        len(rss_articles),
        len(arxiv_articles),
        len(all_articles),
    )
    return all_articles


def _source_weight(article: RawArticle, sources: SourcesConfig) -> float:
    if article.source_type == "rss":
        for s in sources.rss:
            if s.name == article.source_name:
                return s.weight
    elif article.source_type == "arxiv":
        for s in sources.arxiv:
            if s.name == article.source_name:
                return s.weight
    return 1.0


async def run_pipeline(
    *,
    llm: LLMClient,
    line: LinePublisherClient | None,
    dedup: DedupRepo,
    sources: SourcesConfig,
) -> PipelineResult:
    al = get_analytics_logger()
    digest_id = str(uuid.uuid4())
    generated_at = datetime.now(UTC)
    await dedup.create_digest(digest_id, generated_at=generated_at)

    # 1. 収集
    raw_articles = await _collect(sources)
    _emit(
        al,
        action="articles_collected",
        attributes={
            "_resource_id": digest_id,
            "count": len(raw_articles),
            "source_breakdown": {
                st: sum(1 for a in raw_articles if a.source_type == st)
                for st in {a.source_type for a in raw_articles}
            },
        },
    )

    # 個別 article_collected (attributes に content_preview を含む = 分析基盤への主入力)
    for a in raw_articles:
        _emit(
            al,
            action="article_collected",
            attributes={
                "_resource_type": "article",
                "_resource_id": a.article_id,
                "source_type": a.source_type,
                "source_name": a.source_name,
                "url": a.url,
                "url_normalized": a.url_normalized,
                "title": a.title,
                "content_preview": a.content_preview,
                "author": a.author,
                "published_at": a.published_at.isoformat() if a.published_at else None,
                "fetched_at": a.fetched_at.isoformat(),
                "arxiv_primary_category": a.arxiv_primary_category,
                "arxiv_pdf_url": a.arxiv_pdf_url,
            },
        )

    # 2. dedup
    new_ids = await dedup.filter_new_ids(
        (a.article_id for a in raw_articles),
        window_days=settings.dedup_window_days,
    )
    new_articles = [a for a in raw_articles if a.article_id in new_ids]
    logger.info("dedup: new=%d (of %d)", len(new_articles), len(raw_articles))

    if not new_articles:
        await dedup.record_delivery(
            digest_id=digest_id, articles=[], status="empty", note="no new articles"
        )
        _emit(al, action="digest_skipped",
              attributes={"_resource_id": digest_id, "reason": "no_new_articles"})
        await al.flush()
        return PipelineResult(
            digest_id=digest_id, status="empty",
            collected_count=len(raw_articles), new_count=0, scored_count=0,
            passing_count=0, news_count=0, arxiv_count=0,
            line_success=0, line_failure=0,
        )

    # 3. LLM スコアリング (バッチ)
    scores = await scorer.score_articles(llm, new_articles)

    # 4. 要約 + タグ (閾値超過のみに絞って LLM コスト節約)
    curated: list[CuratedArticle] = []
    for a in new_articles:
        s = scores.get(a.article_id)
        if s is None:
            continue
        weight = _source_weight(a, sources)
        final = s.score * weight
        track = "arxiv" if a.source_type == "arxiv" else "news"
        if final < settings.relevance_threshold:
            # 通過しないものは summary/tag 呼ばない (コスト最適化)
            curated.append(
                CuratedArticle(
                    article_id=a.article_id,
                    raw=a,
                    llm_relevance_score=s.score,
                    source_weight=weight,
                    final_score=final,
                    summary_ja="",
                    tags=[],
                    domain=sources.domain,
                    importance_reason=s.reason,
                    track=track,
                )
            )
            continue
        summary = await summarizer.summarize_article(llm, a)
        tags = await tagger.tag_article(llm, a, summary)
        curated.append(
            CuratedArticle(
                article_id=a.article_id,
                raw=a,
                llm_relevance_score=s.score,
                source_weight=weight,
                final_score=final,
                summary_ja=summary,
                tags=tags,
                domain=sources.domain,
                importance_reason=s.reason,
                track=track,
            )
        )
        _emit(
            al,
            action="article_curated",
            attributes={
                "_resource_type": "article",
                "_resource_id": a.article_id,
                "llm_relevance_score": s.score,
                "source_weight": weight,
                "final_score": final,
                "summary_ja": summary,
                "tags": tags,
                "domain": sources.domain,
                "track": track,
                "importance_reason": s.reason,
            },
        )

    passing = [c for c in curated if c.final_score >= settings.relevance_threshold]
    logger.info("scoring: scored=%d passing=%d", len(curated), len(passing))

    # 5. Rank
    digest = ranker.rank(
        curated,
        top_news_n=settings.top_news_n,
        top_arxiv_n=settings.top_arxiv_n,
        relevance_threshold=settings.relevance_threshold,
    )

    # 6. Publish
    line_success = 0
    line_failure = 0
    status: str = "sent"
    note: str | None = None
    if digest.top_news or digest.top_arxiv:
        if line is not None and settings.line_user_id_list:
            flex = build_digest_flex(digest)
            alt = alt_text_for(digest)
            line_success, line_failure = await line.push_flex(
                user_ids=settings.line_user_id_list, alt_text=alt, contents=flex
            )
            if line_success == 0:
                status = "failed"
                note = f"all {line_failure} pushes failed"
        else:
            status = "failed"
            note = "line client or user_ids not configured"
    else:
        status = "empty"
        note = "no passing articles"

    # 7. 結果記録
    delivered_rows = [
        (a.article_id, a.raw.title, a.raw.source_name, a.raw.source_type, a.raw.url_normalized)
        for a in digest.all_articles
    ]
    await dedup.record_delivery(
        digest_id=digest_id,
        articles=delivered_rows if status == "sent" else [],
        status=status,
        note=note,
    )
    _emit(
        al,
        action="digest_delivered",
        attributes={
            "_resource_id": digest_id,
            "status": status,
            "news_count": len(digest.top_news),
            "arxiv_count": len(digest.top_arxiv),
            "line_success": line_success,
            "line_failure": line_failure,
            "article_ids": [a.article_id for a in digest.all_articles],
            "note": note,
        },
        severity="INFO" if status == "sent" else "WARN",
    )
    await al.flush()

    return PipelineResult(
        digest_id=digest_id,
        status=status,
        collected_count=len(raw_articles),
        new_count=len(new_articles),
        scored_count=len(curated),
        passing_count=len(passing),
        news_count=len(digest.top_news),
        arxiv_count=len(digest.top_arxiv),
        line_success=line_success,
        line_failure=line_failure,
    )


# 便利なアクセサ (テスト用)
def load_digest(curated: list[CuratedArticle]) -> Digest:
    return ranker.rank(
        curated,
        top_news_n=settings.top_news_n,
        top_arxiv_n=settings.top_arxiv_n,
        relevance_threshold=settings.relevance_threshold,
    )
