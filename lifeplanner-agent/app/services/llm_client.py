"""lifeplanner 用 LLM クライアント shim。

実体は monorepo root の `llm-client` パッケージに切り出し済み。
本モジュールはそれを lifeplanner の `Settings` + `analytics-platform` logger に
バインドするだけの薄い層として残す。

- `LLMClient` / `AnthropicLLMClient` / `VertexAnthropicLLMClient` / `MockLLMClient`
  / `ChatMessage` は `llm_client` パッケージから直接 re-export
- `build_default_client()` / `get_llm_client()` / `set_llm_client()` は従来通り
  `Settings` を読み、`analytics-platform` の logger を on_call に bind する

呼び出し側の import (`from services.llm_client import ...`) は変更不要。
"""

from __future__ import annotations

import logging

from config import settings

# public re-exports (consumer の import path 維持)
from llm_client import (
    AnthropicLLMClient,
    ChatMessage,
    LLMClient,
    MockLLMClient,
    VertexAnthropicLLMClient,
)
from llm_client.analytics import make_analytics_on_call

logger = logging.getLogger(__name__)


__all__ = [
    "AnthropicLLMClient",
    "ChatMessage",
    "LLMClient",
    "MockLLMClient",
    "VertexAnthropicLLMClient",
    "build_default_client",
    "get_llm_client",
    "set_llm_client",
]


# ---------------------------------------------------------------------------
# analytics 連携 (lifeplanner 固有の logger を渡す)
# ---------------------------------------------------------------------------


def _analytics_logger_factory():
    """`instrumentation.get_analytics_logger()` を lazy に解決する。

    `setup_observability()` 未実行 (CLI 経路等) や取得失敗時は None を返し、
    on_call が noop になる。
    """
    try:
        from instrumentation import get_analytics_logger

        return get_analytics_logger()
    except Exception:
        return None


_on_call = make_analytics_on_call(_analytics_logger_factory)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_default_client() -> LLMClient:
    """環境設定に従い実クライアント or モックを返す。

    - LLM_MOCK_MODE=true → MockLLMClient
    - LLM_PROVIDER=vertex:
        - GOOGLE_CLOUD_PROJECT 未設定 → MockLLMClient (警告ログ)
        - それ以外 → VertexAnthropicLLMClient (ADC 認証)
    - LLM_PROVIDER=anthropic (既定):
        - ANTHROPIC_API_KEY 未設定 → MockLLMClient (警告ログ)
        - それ以外 → AnthropicLLMClient
    """
    if settings.llm_mock_mode:
        logger.info("LLM mock mode enabled")
        return MockLLMClient()

    provider = settings.llm_provider
    if provider == "vertex":
        if not settings.gcp_project_id:
            logger.warning(
                "LLM_PROVIDER=vertex but GOOGLE_CLOUD_PROJECT not set; falling back to MockLLMClient"
            )
            return MockLLMClient()
        logger.info(
            "Using VertexAnthropicLLMClient (project=%s, region=%s, model=%s)",
            settings.gcp_project_id,
            settings.vertex_region,
            settings.llm_model,
        )
        return VertexAnthropicLLMClient(
            project_id=settings.gcp_project_id,
            region=settings.vertex_region,
            model=settings.llm_model,
            max_tokens=settings.llm_max_tokens,
            on_call=_on_call,
        )

    if provider != "anthropic":
        logger.warning(
            "Unknown LLM_PROVIDER=%s; treating as 'anthropic'", provider
        )
    if not settings.anthropic_api_key:
        logger.warning(
            "ANTHROPIC_API_KEY not set; falling back to MockLLMClient"
        )
        return MockLLMClient()
    return AnthropicLLMClient(
        api_key=settings.anthropic_api_key,
        model=settings.llm_model,
        max_tokens=settings.llm_max_tokens,
        on_call=_on_call,
    )


# DI 用の遅延ファクトリ (routes で Depends できる形)
_default_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _default_client
    if _default_client is None:
        _default_client = build_default_client()
    return _default_client


def set_llm_client(client: LLMClient | None) -> None:
    """テストからモックを差し込むための setter。None で既定にリセット。"""
    global _default_client
    _default_client = client
