"""LangGraph Supervisor — Phase 2 範囲 (Intent → RAG / out_of_scope) を構築する。

flow:

    START → classify → ┬─ rag → END
                       └─ out_of_scope → END

注意: Phase 2 は Cloud Run の同期実行で webhook reply まで完結する想定。
LINE 3 秒タイムアウトとぶつかる懸念は proposal §5.4 / DESIGN.md §4 に記載。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fujisawa_platform.knowledge_base import EmbeddingClient, KnowledgeStore
from langgraph.graph import END, START, StateGraph
from llm_client import LLMClient

from app.graph.agents.intent import classify_intent
from app.graph.agents.rag import answer_with_rag
from app.graph.state import InfoBotState

logger = logging.getLogger(__name__)

_OUT_OF_SCOPE_TEXT = (
    "ご質問は藤沢市の公式情報の範囲外でした。\n"
    "防災 / 子育て / ゴミ / 手続き / 観光 / 市政情報 についてお気軽にどうぞ。"
)


@dataclass(frozen=True)
class GraphDependencies:
    """build_graph に DI する依存セット。"""

    llm: LLMClient
    embedding: EmbeddingClient
    store: KnowledgeStore
    top_k: int = 5


def build_graph(deps: GraphDependencies):
    """LangGraph StateGraph を構築して compile したものを返す。"""

    async def _classify_node(state: InfoBotState) -> InfoBotState:
        query = state.get("query", "")
        result = await classify_intent(query, deps.llm)
        return {
            "intent": result.intent,
            "category": result.category,
        }

    async def _rag_node(state: InfoBotState) -> InfoBotState:
        query = state.get("query", "")
        category = state.get("category")
        text, hits = await answer_with_rag(
            query=query,
            embedding=deps.embedding,
            store=deps.store,
            llm=deps.llm,
            top_k=deps.top_k,
            category=category,
        )
        return {
            "rag_hits": hits,
            "final_text": text,
        }

    async def _out_of_scope_node(state: InfoBotState) -> InfoBotState:
        return {"final_text": _OUT_OF_SCOPE_TEXT}

    def _route(state: InfoBotState) -> str:
        return state.get("intent", "rag")

    graph = StateGraph(InfoBotState)
    graph.add_node("classify", _classify_node)
    graph.add_node("rag", _rag_node)
    graph.add_node("out_of_scope", _out_of_scope_node)
    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        _route,
        {"rag": "rag", "out_of_scope": "out_of_scope"},
    )
    graph.add_edge("rag", END)
    graph.add_edge("out_of_scope", END)
    return graph.compile()


async def run_graph(
    *,
    deps: GraphDependencies,
    user_id: str,
    query: str,
) -> str:
    """1 ターンの graph を実行して final_text を返すヘルパ。"""
    compiled = build_graph(deps)
    initial: InfoBotState = {"user_id": user_id, "query": query}
    final = await compiled.ainvoke(initial)
    return final.get("final_text") or _OUT_OF_SCOPE_TEXT


__all__ = ["GraphDependencies", "build_graph", "run_graph"]
