"""Flex Message (carousel) 構築。

LINE Messaging API 仕様:
  - carousel は最大 10 bubble
  - Top 7 (news) + 1 header bubble + arXiv 1-2 で安全に収まる構成にする
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from models import CuratedArticle, Digest

_COLOR_PRIMARY = "#2B2825"
_COLOR_ACCENT_NEWS = "#F4A896"
_COLOR_ACCENT_ARXIV = "#A4C5D8"
_COLOR_MUTED = "#70685E"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _article_bubble(article: CuratedArticle, *, is_arxiv: bool) -> dict[str, Any]:
    color = _COLOR_ACCENT_ARXIV if is_arxiv else _COLOR_ACCENT_NEWS
    track_label = "ARXIV" if is_arxiv else "NEWS"
    source = article.raw.source_name
    title = _truncate(article.raw.title, 80)
    summary = _truncate(article.summary_ja, 140)
    tags_line = "  ".join(f"#{t}" for t in article.tags[:4]) if article.tags else ""
    url = article.raw.arxiv_pdf_url or article.raw.url

    body_contents: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": track_label,
            "size": "xs",
            "color": color,
            "weight": "bold",
        },
        {
            "type": "text",
            "text": title,
            "size": "md",
            "weight": "bold",
            "wrap": True,
            "color": _COLOR_PRIMARY,
            "margin": "sm",
        },
        {
            "type": "text",
            "text": summary,
            "size": "sm",
            "color": _COLOR_PRIMARY,
            "wrap": True,
            "margin": "md",
        },
    ]
    if tags_line:
        body_contents.append(
            {
                "type": "text",
                "text": tags_line,
                "size": "xs",
                "color": _COLOR_MUTED,
                "wrap": True,
                "margin": "md",
            }
        )
    body_contents.append(
        {
            "type": "text",
            "text": source,
            "size": "xs",
            "color": _COLOR_MUTED,
            "margin": "md",
        }
    )

    return {
        "type": "bubble",
        "size": "mega",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": body_contents,
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": color,
                    "action": {"type": "uri", "label": "詳しく読む", "uri": url},
                }
            ],
        },
    }


def _header_bubble(generated_at: datetime, news_count: int, arxiv_count: int) -> dict[str, Any]:
    return {
        "type": "bubble",
        "size": "mega",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": f"📅 {generated_at.strftime('%Y/%m/%d')}",
                    "size": "sm",
                    "color": _COLOR_MUTED,
                },
                {
                    "type": "text",
                    "text": "データ基盤ニュース",
                    "size": "xl",
                    "weight": "bold",
                    "color": _COLOR_PRIMARY,
                    "margin": "sm",
                },
                {
                    "type": "text",
                    "text": f"🏆 TODAY'S TOP {news_count + arxiv_count}",
                    "size": "md",
                    "color": _COLOR_PRIMARY,
                    "margin": "md",
                },
                {
                    "type": "text",
                    "text": f"ニュース {news_count} 本 / arXiv {arxiv_count} 本",
                    "size": "xs",
                    "color": _COLOR_MUTED,
                    "margin": "sm",
                },
            ],
        },
    }


def build_digest_flex(digest: Digest) -> dict[str, Any]:
    """Digest → Flex carousel (最大 10 bubble)。

    LINE Messaging API に直接送信できる contents 辞書を返す。
    """
    bubbles: list[dict[str, Any]] = [
        _header_bubble(
            digest.generated_at,
            news_count=len(digest.top_news),
            arxiv_count=len(digest.top_arxiv),
        )
    ]
    for a in digest.top_news:
        bubbles.append(_article_bubble(a, is_arxiv=False))
    for a in digest.top_arxiv:
        bubbles.append(_article_bubble(a, is_arxiv=True))

    # 上限 10 bubble
    bubbles = bubbles[:10]

    return {"type": "carousel", "contents": bubbles}


def alt_text_for(digest: Digest) -> str:
    total = len(digest.top_news) + len(digest.top_arxiv)
    date = digest.generated_at.strftime("%Y/%m/%d")
    return f"{date} データ基盤ニュース Top {total}"
