"""Anthropic Python SDK ラッパー (Anthropic API 直)。"""

from __future__ import annotations

import time

from ._emit import safe_emit
from ._response import extract_text
from ._system_payload import system_payload
from .types import ChatMessage, OnCallCallback


class AnthropicLLMClient:
    """Anthropic Python SDK ラッパー (Anthropic API 直)。

    使用例:
        client = AnthropicLLMClient(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            model="claude-sonnet-4-6",
            max_tokens=1024,
            on_call=my_analytics_emitter,  # observability 用コールバック (任意)
        )
        text = await client.complete(system="You are...", user="Hi", cache_system=True)
    """

    _PROVIDER = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_tokens: int,
        on_call: OnCallCallback | None = None,
    ) -> None:
        # 依存を関数内で解決 (オフライン時にも import できるよう遅延 import)
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)
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
