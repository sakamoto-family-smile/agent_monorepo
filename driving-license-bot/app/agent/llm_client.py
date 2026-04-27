"""LLM クライアント抽象（Vertex AI Claude をラップする）。

設計（DESIGN.md §4.2）:
- Vertex AI 経由の Claude（asia-northeast1）を採用
- Workload Identity 認証（API キーは持たない）
- prompt caching: system prompt を `cache_control` で固定（呼び出し側で制御）

Protocol で抽象化することで、テスト時は MockLLMClient を DI して LLM 呼び出し
を発生させずに動作確認できる。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import app.config
from app.agent.errors import LLMClientError

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """LLM の生レスポンス（agent 層で JSON parse 等の後段処理を行う）。"""

    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LLMClient(Protocol):
    """テスト容易性のための Protocol。

    `generate` は同期 / 非同期どちらでも実装可能だが、Phase 2 のバッチ駆動
    では同期で十分なため同期にする。webhook 経由の同期生成パスを作る場合は
    別途 async 版を実装する。
    """

    def generate(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 4096,
        temperature: float = 0.4,
        cache_system: bool = True,
    ) -> LLMResponse: ...


class MockLLMClient:
    """テスト用 LLM クライアント。固定レスポンスを返す。

    使い方:
        mock = MockLLMClient(text='{"id": "q_x", ...}')
        result = generator.generate(request)
    """

    def __init__(
        self,
        *,
        text: str = "",
        model: str = "mock-claude",
        input_tokens: int = 100,
        output_tokens: int = 200,
    ) -> None:
        self.text = text
        self.model = model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.calls: list[dict[str, Any]] = []

    def generate(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 4096,
        temperature: float = 0.4,
        cache_system: bool = True,
    ) -> LLMResponse:
        self.calls.append(
            {
                "system": system,
                "user": user,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "cache_system": cache_system,
            }
        )
        return LLMResponse(
            text=self.text,
            model=self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )


class VertexAnthropicClient:
    """Anthropic SDK の Vertex バックエンドを直接利用する実クライアント。

    認証は Workload Identity に委ね、API キーは持たない。リージョンは
    `CLOUD_ML_REGION`（既定: asia-northeast1）。

    NOTE: Phase 2-B 時点では本クラスのインスタンス化を避け、CLI / バッチ
    から個別に build_llm_client() で生成する。テスト・CI ではモック差替。
    """

    def __init__(
        self,
        *,
        project_id: str,
        region: str,
        model: str,
    ) -> None:
        self._project_id = project_id
        self._region = region
        self._model = model
        # 遅延 import（anthropic[vertex] が optional に近い扱いのため）
        try:
            from anthropic import AnthropicVertex  # type: ignore[import-untyped]
        except ImportError as exc:
            raise LLMClientError(
                "anthropic[vertex] is required for VertexAnthropicClient"
            ) from exc
        self._client = AnthropicVertex(project_id=project_id, region=region)
        logger.info(
            "VertexAnthropicClient initialized project=%s region=%s model=%s",
            project_id,
            region,
            model,
        )

    def generate(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 4096,
        temperature: float = 0.4,
        cache_system: bool = True,
    ) -> LLMResponse:
        """Vertex AI 経由で Claude を呼び出す。

        `cache_system=True` の場合、system プロンプトを cache_control で固定。
        Vertex の Claude も Anthropic API と同じ cache_control サポート。
        """
        system_blocks: list[dict[str, Any]] = []
        if cache_system:
            system_blocks.append(
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            )
        else:
            system_blocks.append({"type": "text", "text": system})

        try:
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_blocks,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:  # noqa: BLE001 — SDK の例外は多岐にわたる
            raise LLMClientError(f"Vertex Claude call failed: {exc}") from exc

        # Anthropic レスポンスは content blocks のリスト。テキストブロックを連結。
        text_parts: list[str] = []
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", ""))
        usage = getattr(resp, "usage", None)
        return LLMResponse(
            text="".join(text_parts),
            model=self._model,
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
            cache_read_input_tokens=(
                getattr(usage, "cache_read_input_tokens", 0) if usage else 0
            ),
            cache_creation_input_tokens=(
                getattr(usage, "cache_creation_input_tokens", 0) if usage else 0
            ),
            raw={"id": getattr(resp, "id", "")},
        )


def build_llm_client() -> LLMClient:
    """env から実 LLM クライアントを構築する。

    `VERTEX_CLAUDE_MODEL` / `ANTHROPIC_VERTEX_PROJECT_ID` / `CLOUD_ML_REGION`
    を参照。`AGENT_LLM_MOCK=true` で MockLLMClient（固定空文字列）を返す。
    実運用では呼び出し側が設定しないため、本番経路で誤って Mock が選ばれる
    心配はない（`build_llm_client` を呼ぶのは batch / CLI のみ）。
    """
    settings = app.config.settings
    if settings.agent_llm_mock:
        logger.warning("AGENT_LLM_MOCK=true: returning MockLLMClient (returns empty text)")
        return MockLLMClient(text="", model="mock-claude")
    project = (
        settings.anthropic_vertex_project_id or settings.google_cloud_project
    )
    if not project:
        raise LLMClientError(
            "ANTHROPIC_VERTEX_PROJECT_ID or GOOGLE_CLOUD_PROJECT is required"
        )
    return VertexAnthropicClient(
        project_id=project,
        region=settings.cloud_ml_region,
        model=settings.vertex_claude_model,
    )


__all__ = [
    "LLMClient",
    "LLMResponse",
    "MockLLMClient",
    "VertexAnthropicClient",
    "build_llm_client",
]
