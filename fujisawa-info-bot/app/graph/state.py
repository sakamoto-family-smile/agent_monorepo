"""LangGraph state 定義。

proposal 0004 §4.4 の `InfoBotState` を Phase 2 範囲に絞った形。
Phase 4 (Crawl) / Phase 6 (Emergency) で `crawl_pages` 等を追加していく。
"""

from __future__ import annotations

from typing import Literal, TypedDict

from fujisawa_platform.knowledge_base import SearchHit

Intent = Literal["rag", "out_of_scope"]
"""Phase 2 範囲の分類値。

- `rag`: 公式 HP RAG で答える対象 (default)
- `out_of_scope`: 雑談 / 挨拶 / 範囲外 → 固定文返信
"""


class InfoBotState(TypedDict, total=False):
    """LangGraph の state。 各 node が書き込むキーは optional (total=False)。

    Attributes:
        user_id: LINE userId (sha256 hash 推奨だが Phase 2 は生のまま)
        query: ユーザー発話 (text)
        intent: classify_intent ノードの判定結果
        category: 検索カテゴリ (`disaster` / `parenting` 等)。 None なら全体検索
        rag_hits: KnowledgeStore からの検索結果 top_k
        final_text: LINE に返信する最終テキスト
    """

    user_id: str
    query: str
    intent: Intent
    category: str | None
    rag_hits: list[SearchHit]
    final_text: str


__all__ = ["InfoBotState", "Intent"]
