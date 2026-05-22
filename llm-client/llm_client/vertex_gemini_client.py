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
from .types import ChatMessage, LLMUsage, OnCallCallback


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

        # usage 情報込みで取得 (品質メトリクス / 課金用)
        text, usage = await client.complete_with_usage(
            system="...", user="...", temperature=0.4,
        )
    """

    _PROVIDER = "vertex_gemini"

    def __init__(
        self,
        *,
        project_id: str,
        region: str,
        model: str,
        max_tokens: int,
        temperature: float | None = None,
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
        self._temperature = temperature
        self._on_call = on_call
        self._generative_model_cls = GenerativeModel  # 遅延 instantiate

    async def complete(
        self,
        *,
        system: str,
        user: str,
        cache_system: bool = False,
        temperature: float | None = None,
    ) -> str:
        text, _ = await self.complete_with_usage(
            system=system,
            user=user,
            cache_system=cache_system,
            temperature=temperature,
        )
        return text

    async def complete_messages(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        cache_system: bool = False,
        temperature: float | None = None,
    ) -> str:
        text, _ = await self._complete_messages_with_usage(
            system=system,
            messages=messages,
            cache_system=cache_system,
            temperature=temperature,
        )
        return text

    async def complete_with_usage(
        self,
        *,
        system: str,
        user: str,
        cache_system: bool = False,
        temperature: float | None = None,
    ) -> tuple[str, LLMUsage]:
        """`complete` と同じだが (text, LLMUsage) を返す。

        consumer 側で品質メトリクスや課金計算に token 数を使いたい場合に。
        """
        return await self._complete_messages_with_usage(
            system=system,
            messages=[{"role": "user", "content": user}],
            cache_system=cache_system,
            temperature=temperature,
        )

    async def _complete_messages_with_usage(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        cache_system: bool,
        temperature: float | None,
    ) -> tuple[str, LLMUsage]:
        started = time.monotonic()
        try:
            # GenerativeModel は system_instruction を constructor で受ける
            model_instance = self._generative_model_cls(
                self._model,
                system_instruction=system if system else None,
            )
            contents = _to_gemini_contents(messages)
            gen_config = _build_gen_config(
                max_tokens=self._max_tokens,
                temperature=temperature if temperature is not None else self._temperature,
            )
            resp = await model_instance.generate_content_async(
                contents,
                generation_config=gen_config,
            )
            text = _extract_text(resp)
            usage = _extract_usage(resp, model=self._model)
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
        return text, usage


def _build_gen_config(*, max_tokens: int, temperature: float | None) -> dict[str, Any]:
    cfg: dict[str, Any] = {"max_output_tokens": max_tokens}
    if temperature is not None:
        cfg["temperature"] = temperature
    return cfg


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


def _extract_usage(resp: Any, *, model: str) -> LLMUsage:
    """Gemini レスポンスから usage 情報を抽出。"""
    usage_md = getattr(resp, "usage_metadata", None)
    if usage_md is None:
        return LLMUsage(model=model)
    return LLMUsage(
        model=model,
        input_tokens=int(getattr(usage_md, "prompt_token_count", 0) or 0),
        output_tokens=int(getattr(usage_md, "candidates_token_count", 0) or 0),
    )


__all__ = ["VertexGeminiLLMClient"]
