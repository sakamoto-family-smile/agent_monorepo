"""LLMClient Protocol 定義。"""

from __future__ import annotations

from typing import Protocol

from .types import ChatMessage


class LLMClient(Protocol):
    """LLM 呼出抽象。テストで差し替え可能。

    実装:
      - AnthropicLLMClient: Anthropic API 直叩き
      - VertexAnthropicLLMClient: GCP Vertex AI 経由
      - MockLLMClient: オフライン・テスト用

    prompt caching:
      `cache_system=True` を渡すと system プロンプトを `cache_control=ephemeral`
      でキャッシュ化する。長い静的 system prompt を複数呼出しで再利用する
      相談系機能向け。キャッシュヒット/ミスは `on_call` コールバック経由で
      レスポンスの `usage.cache_read_input_tokens` / `cache_creation_input_tokens`
      を集計する。
    """

    async def complete(
        self,
        *,
        system: str,
        user: str,
        cache_system: bool = False,
    ) -> str: ...

    async def complete_messages(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        cache_system: bool = False,
    ) -> str: ...
