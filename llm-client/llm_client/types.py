"""共有型定義。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, TypedDict


class ChatMessage(TypedDict):
    """複数ターン会話用のメッセージ型。"""

    role: Literal["user", "assistant"]
    content: str


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
