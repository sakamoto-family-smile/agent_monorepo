"""Anthropic Claude API の薄いラッパー。

設計方針:
  - プロトコル `LLMClient.complete(system, user)` を公開
  - 実装は `AnthropicLLMClient` (Anthropic API 直), `VertexAnthropicLLMClient` (GCP Vertex AI 経由), `MockLLMClient` (テスト・オフライン)
  - LLM_MOCK_MODE=true またはプロバイダ認証情報が欠落時は MockLLMClient にフォールバック
  - LLM_PROVIDER で anthropic / vertex を切替 (既定: anthropic)
  - 返り値は plain text (マークダウン想定)
"""

from __future__ import annotations

import logging
from typing import Protocol

from config import settings

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    """LLM 呼出抽象。テストで差し替え可能。"""

    async def complete(self, *, system: str, user: str) -> str: ...


class MockLLMClient:
    """オフライン/テスト用の決定論モック。

    system / user の先頭をエコーしつつ、既定の要約テンプレで返す。
    """

    def __init__(self, fixed_reply: str | None = None) -> None:
        self._fixed = fixed_reply

    async def complete(self, *, system: str, user: str) -> str:
        if self._fixed is not None:
            return self._fixed
        # 入力のごく一部だけ引用し、決定論的な文面を返す
        preview = user.strip().splitlines()[0] if user.strip() else ""
        return (
            "【モック要約】入力の先頭を確認しました: "
            f"{preview[:80]}\n"
            "この応答はモックであり、実際の LLM 出力ではありません。"
        )


def _extract_text(resp) -> str:
    """messages.create のレスポンスから TextBlock を結合して返す共通処理。"""
    parts: list[str] = []
    for block in resp.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "".join(parts).strip()


class AnthropicLLMClient:
    """Anthropic Python SDK ラッパー (Anthropic API 直)。"""

    def __init__(self, *, api_key: str, model: str, max_tokens: int) -> None:
        # 依存を関数内で解決 (オフライン時にも起動できるよう遅延 import)
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    async def complete(self, *, system: str, user: str) -> str:
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return _extract_text(resp)


class VertexAnthropicLLMClient:
    """Anthropic Python SDK (AsyncAnthropicVertex) ラッパー (GCP Vertex AI 経由)。

    認証は ADC (Application Default Credentials) を使用:
      - ローカル: `gcloud auth application-default login`
      - Cloud Run 等: サービスアカウントに `roles/aiplatform.user`
    モデル名は Vertex 形式 (例: `claude-sonnet-4-6@20250929`) を指定する。
    """

    def __init__(self, *, project_id: str, region: str, model: str, max_tokens: int) -> None:
        from anthropic import AsyncAnthropicVertex

        self._client = AsyncAnthropicVertex(project_id=project_id, region=region)
        self._model = model
        self._max_tokens = max_tokens

    async def complete(self, *, system: str, user: str) -> str:
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return _extract_text(resp)


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
