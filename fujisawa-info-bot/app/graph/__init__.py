"""LangGraph Supervisor + sub-agent。

Phase 2: Intent (分類) + RAG (検索 + 出典付き回答) の 2 node 構成。
Phase 4+ で Crawl / Emergency を追加していく。

公開 API:
- `InfoBotState`: graph state TypedDict
- `Intent`: 分類カテゴリ literal
- `build_graph`: コンパイル済 StateGraph を返すファクトリ
- `run_graph`: state 初期値を受けて回答テキスト + 出典を返すヘルパ
"""

from __future__ import annotations

from app.graph.state import InfoBotState, Intent
from app.graph.supervisor import GraphDependencies, build_graph, run_graph

__all__ = [
    "GraphDependencies",
    "InfoBotState",
    "Intent",
    "build_graph",
    "run_graph",
]
