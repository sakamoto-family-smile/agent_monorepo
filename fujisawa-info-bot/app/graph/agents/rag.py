"""RAG sub-agent — KnowledgeStore 検索 + LLM 整形 + 出典付き回答生成。

flow:
1. EmbeddingClient で query → vector
2. KnowledgeStore.search_pages(query_vector, top_k, category) で top-k 取得
3. ヒット 0 件 → 「公式 HP では該当ページが見つかりませんでした」固定文
4. LLM に hits の content + URL を渡し、 出典 URL 付きで回答整形

出典の付与は LLM 任せにせず、 本ファイル側でフッターとして 1〜N 個の URL を
末尾に append する (LLM 出力の verify を最小化する設計)。
"""

from __future__ import annotations

import logging

from fujisawa_platform.knowledge_base import (
    EmbeddingClient,
    KnowledgeStore,
    SearchHit,
)
from llm_client import LLMClient

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
あなたは藤沢市の公式 HP に基づいて市民の質問に答える LINE Bot です。

与えられた `公式ページの抜粋` のみを根拠に、 200 字以内で簡潔に回答してください。
- 推測 / 一般論 / 不確かな情報は書かない
- 公式ページの抜粋に答えが含まれていない場合は、 その旨を率直に書く
- 出典 URL はあなたが書かなくてよい (システムが末尾に自動で付与する)
- やさしい日本語を心がけ、 敬体 (です・ます調)
"""

_NO_HIT_TEXT = (
    "申し訳ありません、 藤沢市公式 HP から該当する情報が見つかりませんでした。\n"
    "公式コンタクトセンター (0466-50-3500) にお問い合わせください。"
)


async def answer_with_rag(
    *,
    query: str,
    embedding: EmbeddingClient,
    store: KnowledgeStore,
    llm: LLMClient,
    top_k: int = 5,
    category: str | None = None,
) -> tuple[str, list[SearchHit]]:
    """RAG 1 ターン実行。

    Returns:
        (final_text, hits): hits は最終 prompt に使った top-k (出典表示用)
    """
    if not query.strip():
        return (_NO_HIT_TEXT, [])

    query_vec = embedding.embed(query)
    hits = await store.search_pages(query_vec, top_k=top_k, category=category)

    # category 指定で 0 hit のときは category=None で全体検索 fallback。
    # weekly_crawl が category 列を自動付与しない現状 (全行 NULL) で、
    # Intent agent の category 推定が空振りするとそのまま 0 hit になり
    # 「該当ページ無し」 を返してしまうため、 category なし再検索で救う。
    # weekly_crawl の category 自動付与 (follow-up backlog) 完了後は本 fallback
    # を撤去するか re-rank ロジックに置換する。
    if not hits and category is not None:
        logger.info(
            "answer_with_rag: 0 hits with category=%r, retrying without category",
            category,
        )
        hits = await store.search_pages(query_vec, top_k=top_k, category=None)

    if not hits:
        return (_NO_HIT_TEXT, [])

    user_prompt = _build_user_prompt(query, hits)
    try:
        body = await llm.complete(system=_SYSTEM_PROMPT, user=user_prompt)
    except Exception:  # noqa: BLE001 — fallback で出典のみ提示
        logger.exception("answer_with_rag: LLM call failed")
        body = "情報を整理する処理が失敗しました。 下記の出典をご確認ください。"

    footer = _format_citations(hits)
    return (f"{body.strip()}\n\n{footer}", hits)


def _build_user_prompt(query: str, hits: list[SearchHit]) -> str:
    excerpts = []
    for i, hit in enumerate(hits, start=1):
        title = hit.page.title or "(タイトル無し)"
        excerpt = hit.page.content.strip()
        if len(excerpt) > 800:
            excerpt = excerpt[:800] + "…"
        excerpts.append(f"[{i}] {title}\n{excerpt}")

    joined = "\n\n".join(excerpts)
    return (
        f"# 質問\n{query.strip()}\n\n"
        f"# 公式ページの抜粋\n{joined}\n"
    )


def _format_citations(hits: list[SearchHit]) -> str:
    """出典フッタを生成。 重複 URL は除外して最大 3 個に絞る。"""
    seen: set[str] = set()
    lines: list[str] = ["出典:"]
    for hit in hits:
        url = str(hit.page.url)
        if url in seen:
            continue
        seen.add(url)
        lines.append(f"・{url}")
        if len(lines) > 3:  # ヘッダ "出典:" + 3 URL
            break
    return "\n".join(lines)


__all__ = ["answer_with_rag"]
