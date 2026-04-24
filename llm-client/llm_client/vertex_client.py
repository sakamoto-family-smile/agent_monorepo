"""Anthropic Python SDK (AsyncAnthropicVertex) ラッパー (GCP Vertex AI 経由)。"""

from __future__ import annotations

import time

from ._emit import safe_emit
from ._response import extract_text
from ._system_payload import system_payload
from .types import ChatMessage, OnCallCallback


class VertexAnthropicLLMClient:
    """Anthropic Python SDK (AsyncAnthropicVertex) ラッパー。

    認証は ADC (Application Default Credentials) を使用:
      - ローカル: `gcloud auth application-default login`
      - Cloud Run 等: サービスアカウントに `roles/aiplatform.user`
    モデル名は Vertex 形式 (例: `claude-sonnet-4-6@20250929`) を指定する。
    """

    _PROVIDER = "vertex"

    def __init__(
        self,
        *,
        project_id: str,
        region: str,
        model: str,
        max_tokens: int,
        on_call: OnCallCallback | None = None,
    ) -> None:
        from anthropic import AsyncAnthropicVertex

        self._client = AsyncAnthropicVertex(project_id=project_id, region=region)
        self._model = model
        self._max_tokens = max_tokens
        self._on_call = on_call

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
            resp = await self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system_payload(system, cache=cache_system),
                messages=list(messages),
            )
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
        return extract_text(resp)
