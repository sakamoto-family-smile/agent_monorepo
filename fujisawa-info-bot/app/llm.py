"""LLMClient ファクトリ。

`settings.llm_provider` を見て `MockLLMClient` か `VertexAnthropicLLMClient`
を生成する。 本ファイルはシングルトンを保持しない (テストでの差し替えやすさ
優先)。 routes / graph 層で startup 時に 1 度だけ生成して使い回す想定。
"""

from __future__ import annotations

from llm_client import LLMClient, MockLLMClient

from app.config import Settings


def build_llm_client(settings: Settings) -> LLMClient:
    """`settings.llm_provider` に応じて LLMClient を返す。

    - `mock`: テスト / 開発 default。 `MockLLMClient` を返す
    - `vertex_anthropic`: 本番。 ADC + Vertex AI 経由 Claude
    """
    if settings.llm_provider == "mock":
        return MockLLMClient()
    if settings.llm_provider == "vertex_anthropic":
        # 本番 import は呼出時 lazy。 vertex extras が入っていなくても
        # mock provider なら起動できるようにする。
        from llm_client import VertexAnthropicLLMClient

        if not settings.gcp_project_id:
            raise RuntimeError(
                "FUJISAWA_INFO_BOT_GCP_PROJECT_ID is required when llm_provider=vertex_anthropic"
            )
        return VertexAnthropicLLMClient(
            project_id=settings.gcp_project_id,
            region=settings.vertex_region,
            model=settings.anthropic_model,
            max_tokens=settings.llm_max_tokens,
        )
    raise ValueError(f"unknown llm_provider: {settings.llm_provider}")


__all__ = ["build_llm_client"]
