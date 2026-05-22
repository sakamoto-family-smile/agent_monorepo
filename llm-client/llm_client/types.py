"""共有型定義。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, TypedDict


class ChatMessage(TypedDict):
    """複数ターン会話用のメッセージ型。"""

    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class LLMUsage:
    """LLM 呼出 1 回分の usage / コストメタデータ。

    `complete_with_usage()` の戻り値 2nd 要素。 consumer (driving-license-bot 等)
    が品質メトリクスや課金計算に使う。

    cache 系 4 フィールドは Anthropic で意味を持つ。 Gemini は cache_creation /
    cache_read を区別しないため両方 0 となる (将来 Vertex context caching API
    対応時に拡張)。
    """

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


class LlmCallEvent(TypedDict, total=False):
    """`on_call` コールバックに渡すイベント辞書。

    consumer がこれを受け取り、analytics-platform や自前のロガーに
    emit する。llm-client 側は analytics-platform に依存しない。
    """

    provider: str
    model: str
    resp: Any            # anthropic SDK のレスポンスオブジェクト (使用者が usage/stop_reason を読む)
    latency_ms: int
    error: Exception | None


OnCallCallback = Callable[[LlmCallEvent], None]
"""LLM 呼出 1 回ごとに呼ばれるコールバック。observability 用途。

例外を握り潰して呼び出し側には伝播させない (コールバック失敗で本処理が止まらないように)。
"""
