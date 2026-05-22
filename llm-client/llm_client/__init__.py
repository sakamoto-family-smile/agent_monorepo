"""Thin Claude / Gemini API wrapper for monorepo-wide reuse.

主な型とクライアント:
  - `LLMClient` Protocol (complete / complete_messages)
  - `AnthropicLLMClient` (Anthropic API 直)
  - `VertexAnthropicLLMClient` (GCP Vertex AI 経由 Anthropic Claude)
  - `VertexGeminiLLMClient` (GCP Vertex AI 経由 Google Gemini)
  - `MockLLMClient` (テスト・オフライン)

prompt caching:
  `cache_system=True` を渡すと system プロンプトを `cache_control=ephemeral` 化
  (Anthropic 系のみ。 Gemini は no-op で将来対応予定)。

observability:
  `on_call` コールバックで呼び出し毎にイベントを受け取れる。
  `analytics.make_analytics_on_call()` で analytics-platform 連携の雛形を取得可能。
"""

from ._system_payload import system_payload
from .anthropic_client import AnthropicLLMClient
from .mock import MockLLMClient
from .protocol import LLMClient
from .types import ChatMessage, LlmCallEvent, LLMUsage, OnCallCallback
from .vertex_client import VertexAnthropicLLMClient
from .vertex_gemini_client import VertexGeminiLLMClient

__all__ = [
    "AnthropicLLMClient",
    "ChatMessage",
    "LLMClient",
    "LLMUsage",
    "LlmCallEvent",
    "MockLLMClient",
    "OnCallCallback",
    "VertexAnthropicLLMClient",
    "VertexGeminiLLMClient",
    "system_payload",
]
