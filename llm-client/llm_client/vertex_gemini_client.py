"""Vertex AI Gemini (google-cloud-aiplatform) ラッパー。

`LLMClient` Protocol に準拠した薄ラッパ。 Vertex Gemini の generative_models
SDK を使い、 Anthropic 系クライアント (VertexAnthropicLLMClient) と同じ
`complete` / `complete_messages` インタフェースを公開する。

認証: ADC (Application Default Credentials)。 Cloud Run 等では SA に
`roles/aiplatform.user` が必要。

依存: `google-cloud-aiplatform` (vertexai)。 install 時に extra で入れる想定:
    pip install "llm-client[vertex-gemini]"

cache_system 引数は受け取るが現状 no-op (Gemini は Anthropic 風の `cache_control`
を持たない。 Vertex 側の context caching API は別 PR で対応予定)。
"""

from __future__ import annotations

import time
from typing import Any

from ._emit import safe_emit
from .types import ChatMessage, OnCallCallback


class VertexGeminiLLMClient:
    """Vertex AI Gemini ラッパー (`LLMClient` Protocol 準拠)。

    Example:
        client = VertexGeminiLLMClient(
            project_id="my-project",
            region="asia-northeast1",
            model="gemini-2.5-flash",
            max_tokens=2048,
        )
        text = await client.complete(system="あなたは...", user="質問")
    """

    _PROVIDER = "vertex_gemini"

    def __init__(
        self,
        *,
        project_id: str,
        region: str,
        model: str,
        max_tokens: int,
        on_call: OnCallCallback | None = None,
    ) -> None:
        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel
        except ImportError as err:
            raise ImportError(
                "VertexGeminiLLMClient requires `google-cloud-aiplatform`. "
                "Install with: `pip install 'llm-client[vertex-gemini]'`"
            ) from err

        vertexai.init(project=project_id, location=region)
        self._project_id = project_id
        self._region = region
        self._model = model
        self._max_tokens = max_tokens
        self._on_call = on_call
        self._generative_model_cls = GenerativeModel  # 遅延 instantiate

    async def complete(
        self,
        *,
        system: str,
        user: str,
        cache_system: bool = False,
    ) -> str:
        return await self.complete_messages(
            system=system,
            messages=[{"role": "user", "content": user}],
            cache_system=cache_system,
        )

    async def complete_messages(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        cache_system: bool = False,
    ) -> str:
        started = time.monotonic()
        try:
            # GenerativeModel は system_instruction を constructor で受ける
            model_instance = self._generative_model_cls(
                self._model,
                system_instruction=system if system else None,
            )
            contents = _to_gemini_contents(messages)
            resp = await model_instance.generate_content_async(
                contents,
                generation_config={"max_output_tokens": self._max_tokens},
            )
            text = _extract_text(resp)
        except Exception as e:
            safe_emit(
                self._on_call,
                provider=self._PROVIDER,
                model=self._model,
                resp=None,
                started=started,
                error=e,
            )
            raise
        safe_emit(
            self._on_call,
            provider=self._PROVIDER,
            model=self._model,
            resp=resp,
            started=started,
            error=None,
        )
        return text


def _to_gemini_contents(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    """Anthropic 風 ChatMessage を Gemini 風 contents 配列に変換。

    role: "user" → "user"、 "assistant" → "model"。
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        out.append({"role": role, "parts": [{"text": m["content"]}]})
    return out


def _extract_text(resp: Any) -> str:
    """Gemini レスポンスから text を抽出。 candidates[0].content.parts[*].text を結合。"""
    try:
        # SDK が `text` property を提供している場合
        if hasattr(resp, "text") and resp.text:
            return str(resp.text)
    except (ValueError, AttributeError):
        pass

    parts_text: list[str] = []
    for candidate in getattr(resp, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        if content is None:
            continue
        for part in getattr(content, "parts", []) or []:
            t = getattr(part, "text", None)
            if t:
                parts_text.append(t)
    return "".join(parts_text)


__all__ = ["VertexGeminiLLMClient"]
