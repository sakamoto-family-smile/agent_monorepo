"""Thin Anthropic Claude API wrapper for monorepo-wide reuse.

主な型とクライアント:
  - `LLMClient` Protocol (complete / complete_messages)
  - `AnthropicLLMClient` (Anthropic API 直)
  - `VertexAnthropicLLMClient` (GCP Vertex AI)
  - `MockLLMClient` (テスト・オフライン)

prompt caching:
  `cache_system=True` を渡すと system プロンプトを `cache_control=ephemeral` 化。

observability:
  `on_call` コールバックで呼び出し毎にイベントを受け取れる。
  `analytics.make_analytics_on_call()` で analytics-platform 連携の雛形を取得可能。
"""

from ._system_payload import system_payload
from .anthropic_client import AnthropicLLMClient
from .mock import MockLLMClient
from .protocol import LLMClient
from .types import ChatMessage, LlmCallEvent, OnCallCallback
from .vertex_client import VertexAnthropicLLMClient

__all__ = [
    "AnthropicLLMClient",
    "ChatMessage",
    "LLMClient",
    "LlmCallEvent",
    "MockLLMClient",
    "OnCallCallback",
    "VertexAnthropicLLMClient",
    "system_payload",
]
