"""ドメインモデル (Pydantic)。

RawArticle: Collector が返す生データ (source_type / url / title / content など)
CuratedArticle: Curator が LLM で処理した結果 (score / summary / tags / domain)
DigestEntry: Ranker が選んだ最終配信エントリ + Publisher が使う表示フィールド
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SourceType = Literal["rss", "arxiv"]


class RawArticle(BaseModel):
    """Collector 出力: 1 ソース 1 記事の生データ。"""

    model_config = ConfigDict(frozen=True)

    # 本番は url_normalizer.article_id() が 32 字の hex を生成。
    # min_length=1 に緩めてテスト用の短縮 ID も受け入れる。
    article_id: str = Field(..., min_length=1, max_length=64)
    source_type: SourceType
    source_name: str
    url: str
    url_normalized: str
    title: str
    content: str = ""                   # RSS は summary 数百字、arXiv は abstract
    content_preview: str = ""           # 500 字以内
    author: str | None = None
    published_at: datetime | None = None
    fetched_at: datetime
    # arXiv 固有
    arxiv_primary_category: str | None = None
    arxiv_pdf_url: str | None = None


class CuratedArticle(BaseModel):
    """Curator 出力: LLM スコアリング・要約・タグ付け済み。"""

    model_config = ConfigDict(frozen=True)

    article_id: str
    raw: RawArticle
    llm_relevance_score: float = Field(..., ge=0.0, le=10.0)
    source_weight: float = Field(..., ge=0.0, le=3.0)
    final_score: float = Field(..., ge=0.0)
    summary_ja: str
    tags: list[str] = Field(default_factory=list)
    domain: str = "data_platform"
    importance_reason: str | None = None
    track: Literal["news", "arxiv"]


class Digest(BaseModel):
    """Ranker 出力: 1 回の配信候補セット。"""

    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    top_news: list[CuratedArticle]
    top_arxiv: list[CuratedArticle]

    @property
    def all_articles(self) -> list[CuratedArticle]:
        return list(self.top_news) + list(self.top_arxiv)
