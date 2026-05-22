"""LLM クライアント抽象（Vertex AI Claude / Gemini をラップする）。

設計（DESIGN.md §4.2）:
- Vertex AI 経由の Claude（asia-northeast1）を採用
- Workload Identity 認証（API キーは持たない）
- prompt caching: system prompt を `cache_control` で固定（呼び出し側で制御）

Protocol で抽象化することで、 テスト時は MockLLMClient を DI して LLM 呼び出し
を発生させずに動作確認できる。

2026-05-22: `VertexGeminiClient` を `llm-client` パッケージ
(`VertexGeminiLLMClient`) の thin wrapper に置換 (PR-150 follow-up)。 monorepo
内の Gemini 呼出経路を一本化する。 sync ⇄ async ブリッジは `_run_async()`。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import app.config
from app.agent.errors import LLMClientError

logger = logging.getLogger(__name__)

def _run_async[T](coro: Awaitable[T]) -> T:
    """sync コンテキストから async coroutine を実行する。

    - 現在の thread に走っている event loop が無ければ `asyncio.run` で実行
    - 既に loop が走っている (例: FastAPI 内 → pipeline.run async → review sync)
      なら、 別 thread で新規 loop を起こして実行する (`asyncio.run` は
      RuntimeError になるため)。 thread overhead は LLM 呼出本体 (数秒) に
      比較すれば無視できる
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop in this thread → safe to use asyncio.run
        return asyncio.run(coro)

    # Running loop in current thread → bridge via separate thread
    result: dict[str, Any] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coro)  # type: ignore[arg-type]
        except BaseException as exc:  # noqa: BLE001
            result["error"] = exc

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join()
    if "error" in result:
        raise result["error"]
    return result["value"]  # type: ignore[no-any-return]


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


class VertexGeminiClient:
    """Gemini on Vertex AI の同期クライアント。 Quality Reviewer の cross-check 用。

    Question Generator が Claude である一方、 Quality Reviewer は意図的に
    別系列 (Gemini) を使うことで、 共通モード失敗を検出可能にする
    (DESIGN.md §3.2 / §3.1.1)。

    実装: 2026-05-22 から shared な `llm-client` パッケージの
    `VertexGeminiLLMClient` を内部で使う。 driving-license-bot の sync API
    (`LLMClient` Protocol) との互換性のため、 内部の async 呼出を
    `_run_async()` で synchronously ブリッジする。

    `cache_system` は Anthropic 風 prompt caching のフラグで Gemini では no-op。
    context caching API 対応時に拡張予定 (proposal-level 検討事項)。
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
        try:
            from llm_client import VertexGeminiLLMClient as _Inner
        except ImportError as exc:  # pragma: no cover — llm-client 未導入時
            raise LLMClientError(
                "llm-client (with [vertex-gemini] extra) is required for VertexGeminiClient"
            ) from exc

        # llm-client 側の max_tokens は constructor で固定するため、 generate()
        # の per-call max_tokens は llm-client 側に毎回 instance を作り直すと
        # 重い。 そのため後段で max_tokens / temperature を per-call override する
        # ため、 ここでは consumer 提供 default を仮置きする。
        self._inner = _Inner(
            project_id=project_id,
            region=region,
            model=model,
            max_tokens=4096,
        )
        logger.info(
            "VertexGeminiClient initialized via llm-client.VertexGeminiLLMClient "
            "(project=%s region=%s model=%s)",
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
        cache_system: bool = True,  # noqa: ARG002 — Gemini は Anthropic と異なるキャッシュ方式
    ) -> LLMResponse:
        """Vertex AI 経由で Gemini を呼び出す (sync ラッパ)。

        内部実装は `llm_client.VertexGeminiLLMClient.complete_with_usage()` で、
        text + token usage を取得して `LLMResponse` を組み立てる。
        """
        # per-call max_tokens override
        self._inner._max_tokens = max_tokens  # noqa: SLF001 — driving-license-bot 側で per-call 上書きが必要なため

        try:
            text, usage = _run_async(
                self._inner.complete_with_usage(
                    system=system,
                    user=user,
                    temperature=temperature,
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMClientError(f"Vertex Gemini call failed: {exc}") from exc

        return LLMResponse(
            text=text,
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_input_tokens=usage.cache_read_input_tokens,
            cache_creation_input_tokens=usage.cache_creation_input_tokens,
        )


def build_llm_client() -> LLMClient:
    """env から Question Generator 用 LLM クライアントを構築する。

    `AGENT_LLM_PROVIDER` で claude / gemini を切替（既定: gemini）。Claude は
    Vertex AI Marketplace 承認が必要なため、承認前は gemini にしておく。
    `AGENT_LLM_MOCK=true` で MockLLMClient を返す（CI / 開発の安全弁）。

    切替例:
      AGENT_LLM_PROVIDER=claude make vertex-verify   # 承認後の本番化
      AGENT_LLM_PROVIDER=gemini make vertex-verify   # 既定 (Marketplace 不要)
    """
    settings = app.config.settings
    if settings.agent_llm_mock:
        logger.warning(
            "AGENT_LLM_MOCK=true: returning MockLLMClient (returns empty text)"
        )
        return MockLLMClient(text="", model="mock")

    project = settings.anthropic_vertex_project_id or settings.google_cloud_project
    if not project:
        raise LLMClientError(
            "ANTHROPIC_VERTEX_PROJECT_ID or GOOGLE_CLOUD_PROJECT is required"
        )

    provider = settings.agent_llm_provider.strip().lower()
    if provider == "gemini":
        logger.info(
            "AGENT_LLM_PROVIDER=gemini: question generator uses Vertex Gemini "
            "(cross-check value reduced; rely on human review)"
        )
        return VertexGeminiClient(
            project_id=project,
            region=settings.cloud_ml_region,
            model=settings.vertex_gemini_model,
        )
    if provider == "claude":
        return VertexAnthropicClient(
            project_id=project,
            region=settings.cloud_ml_region,
            model=settings.vertex_claude_model,
        )
    raise LLMClientError(
        f"unsupported agent_llm_provider: {provider!r} (expected 'claude' or 'gemini')"
    )


def build_reviewer_llm_client() -> LLMClient:
    """env から Gemini クライアントを構築する（Quality Reviewer 用）。

    別系列モデル（Claude vs Gemini）を意図的に分けて cross-check する設計。
    `AGENT_LLM_MOCK=true` で Mock。
    """
    settings = app.config.settings
    if settings.agent_llm_mock:
        logger.warning(
            "AGENT_LLM_MOCK=true: returning MockLLMClient for reviewer"
        )
        return MockLLMClient(text="", model="mock-gemini")
    project = settings.google_cloud_project
    if not project:
        raise LLMClientError("GOOGLE_CLOUD_PROJECT is required for Gemini reviewer")
    return VertexGeminiClient(
        project_id=project,
        region=settings.cloud_ml_region,
        model=settings.vertex_gemini_model,
    )


__all__ = [
    "LLMClient",
    "LLMResponse",
    "MockLLMClient",
    "VertexAnthropicClient",
    "VertexGeminiClient",
    "build_llm_client",
    "build_reviewer_llm_client",
]
