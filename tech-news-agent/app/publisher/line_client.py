"""LINE Messaging API クライアント (Push 専用)。

Phase 1 は Reply は使わない (webhook 未稼働)。Phase 2 で webhook 有効化時に
reply_message を別メソッドで追加する。
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class LinePublisherClient(Protocol):
    """Push 専用インタフェース (テスト差替え容易)。"""

    async def push_flex(
        self, *, user_ids: list[str], alt_text: str, contents: dict[str, Any]
    ) -> tuple[int, int]:
        """push 結果 (success_count, failure_count) を返す。"""

    async def push_text(self, *, user_ids: list[str], text: str) -> tuple[int, int]:
        ...

    async def close(self) -> None: ...


class LineBotSdkClient:
    def __init__(self, *, channel_access_token: str) -> None:
        from linebot.v3.messaging import (  # noqa: PLC0415
            AsyncApiClient,
            AsyncMessagingApi,
            Configuration,
        )

        self._config = Configuration(access_token=channel_access_token)
        self._api_client = AsyncApiClient(self._config)
        self._messaging = AsyncMessagingApi(self._api_client)

    async def push_flex(
        self, *, user_ids: list[str], alt_text: str, contents: dict[str, Any]
    ) -> tuple[int, int]:
        from linebot.v3.messaging import (  # noqa: PLC0415
            FlexContainer,
            FlexMessage,
            PushMessageRequest,
        )

        if not user_ids:
            return (0, 0)
        container = FlexContainer.from_dict(contents)
        trimmed_alt = (alt_text[:400]) or "(no alt)"
        sent = 0
        failed = 0
        for uid in user_ids:
            try:
                await self._messaging.push_message(
                    PushMessageRequest(
                        to=uid,
                        messages=[FlexMessage(alt_text=trimmed_alt, contents=container)],
                    )
                )
                sent += 1
            except Exception as exc:
                failed += 1
                logger.error(
                    "LINE flex push failed uid_prefix=%s error=%s", uid[:4], exc
                )
        return (sent, failed)

    async def push_text(self, *, user_ids: list[str], text: str) -> tuple[int, int]:
        from linebot.v3.messaging import (  # noqa: PLC0415
            PushMessageRequest,
            TextMessage,
        )

        if not user_ids:
            return (0, 0)
        trimmed = text if len(text) <= 4900 else text[:4880] + "\n…(以下省略)"
        sent = 0
        failed = 0
        for uid in user_ids:
            try:
                await self._messaging.push_message(
                    PushMessageRequest(
                        to=uid, messages=[TextMessage(text=trimmed)]
                    )
                )
                sent += 1
            except Exception as exc:
                failed += 1
                logger.error("LINE text push failed uid_prefix=%s error=%s", uid[:4], exc)
        return (sent, failed)

    async def close(self) -> None:
        try:
            await self._api_client.close()
        except Exception:
            pass


_default_client: LinePublisherClient | None = None


def build_default_client(
    channel_secret: str, channel_access_token: str
) -> LinePublisherClient | None:
    if not channel_secret or not channel_access_token:
        logger.warning(
            "LINE_CHANNEL_SECRET or LINE_CHANNEL_ACCESS_TOKEN not set; LINE publish disabled"
        )
        return None
    return LineBotSdkClient(channel_access_token=channel_access_token)


def get_line_client(
    channel_secret: str, channel_access_token: str
) -> LinePublisherClient | None:
    global _default_client
    if _default_client is None:
        _default_client = build_default_client(channel_secret, channel_access_token)
    return _default_client


def set_line_client(client: LinePublisherClient | None) -> None:
    global _default_client
    _default_client = client
