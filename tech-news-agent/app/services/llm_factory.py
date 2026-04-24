"""llm-client のファクトリ。tech-news 固有の Settings を解決して実クライアントを返す。

analytics-platform 連携は `llm_client.analytics.make_analytics_on_call` を使用。
`instrumentation.get_analytics_logger()` が未初期化でも落ちないよう lazy 解決。
"""

from __future__ import annotations

import logging

from llm_client import (
    AnthropicLLMClient,
    LLMClient,
    MockLLMClient,
    VertexAnthropicLLMClient,
)
from llm_client.analytics import make_analytics_on_call

from config import settings

logger = logging.getLogger(__name__)


def _analytics_logger_factory():
    try:
        from instrumentation import get_analytics_logger  # noqa: PLC0415

        return get_analytics_logger()
    except Exception:
        return None


_on_call = make_analytics_on_call(_analytics_logger_factory)


def build_llm_client() -> LLMClient:
    if settings.llm_mock_mode:
        logger.info("LLM mock mode enabled")
        return MockLLMClient()

    provider = settings.llm_provider
    if provider == "vertex":
        if not settings.google_cloud_project:
            logger.warning(
                "LLM_PROVIDER=vertex but GOOGLE_CLOUD_PROJECT not set; falling back to MockLLMClient"
            )
            return MockLLMClient()
        return VertexAnthropicLLMClient(
            project_id=settings.google_cloud_project,
            region=settings.vertex_region,
            model=settings.llm_model,
            max_tokens=settings.llm_max_tokens,
            on_call=_on_call,
        )

    if provider != "anthropic":
        logger.warning("Unknown LLM_PROVIDER=%s; treating as 'anthropic'", provider)
    if not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY not set; falling back to MockLLMClient")
        return MockLLMClient()

    return AnthropicLLMClient(
        api_key=settings.anthropic_api_key,
        model=settings.llm_model,
        max_tokens=settings.llm_max_tokens,
        on_call=_on_call,
    )
