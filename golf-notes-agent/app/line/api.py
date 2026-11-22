"""LINE Messaging API の呼び出し (reply / push / コンテンツの取得)。

テストは ``LineApi`` を満たす偽物を create_app に渡す。
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api.line.me"
DATA_BASE = "https://api-data.line.me"
TIMEOUT = httpx.Timeout(10.0, read=60.0)
MAX_TEXT = 4900


class LineApiError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"LINE API {status}: {detail}")
        self.status = status


@dataclass(frozen=True)
class Download:
    content_type: str
    size_bytes: int
    sha256: str


class LineApi(Protocol):
    async def reply(self, reply_token: str, messages: list[dict[str, Any]]) -> None: ...

    async def push(self, to: str, messages: list[dict[str, Any]], retry_key: str) -> None: ...

    async def transcoding_status(self, message_id: str) -> str:
        """動画・音声の変換の状態。processing | succeeded | failed"""

    async def download(self, message_id: str, dest: Path) -> Download: ...


class HttpLineApi:
    def __init__(self, access_token: str, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=TIMEOUT)
        self._headers = {"Authorization": f"Bearer {access_token}"}

    async def close(self) -> None:
        await self._client.aclose()

    async def _post(self, path: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> None:
        res = await self._client.post(
            f"{API_BASE}{path}", json=payload, headers={**self._headers, **(headers or {})}
        )
        # 409 は同じ X-Line-Retry-Key の push が送信済み (二重送信にならない)
        if res.status_code == 409 and headers and "X-Line-Retry-Key" in headers:
            return
        if res.status_code >= 400:
            raise LineApiError(res.status_code, res.text[:200])

    async def reply(self, reply_token: str, messages: list[dict[str, Any]]) -> None:
        await self._post("/v2/bot/message/reply", {"replyToken": reply_token, "messages": messages})

    async def push(self, to: str, messages: list[dict[str, Any]], retry_key: str) -> None:
        await self._post(
            "/v2/bot/message/push",
            {"to": to, "messages": messages},
            headers={"X-Line-Retry-Key": retry_key},
        )

    async def transcoding_status(self, message_id: str) -> str:
        res = await self._client.get(
            f"{DATA_BASE}/v2/bot/message/{message_id}/content/transcoding", headers=self._headers
        )
        if res.status_code >= 400:
            raise LineApiError(res.status_code, res.text[:200])
        return str(res.json().get("status", "failed"))

    async def download(self, message_id: str, dest: Path) -> Download:
        # 受け取りながら sha256 を計算する (動画をあとから読み直してイベントループを止めない)
        digest = hashlib.sha256()
        size = 0
        async with self._client.stream(
            "GET", f"{DATA_BASE}/v2/bot/message/{message_id}/content", headers=self._headers
        ) as res:
            if res.status_code >= 400:
                raise LineApiError(res.status_code, (await res.aread()).decode(errors="replace")[:200])
            with dest.open("wb") as f:
                async for chunk in res.aiter_bytes():
                    f.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            content_type = res.headers.get("content-type", "application/octet-stream")
        return Download(content_type=content_type.split(";")[0].strip(), size_bytes=size, sha256=digest.hexdigest())


def text(body: str, quick_reply: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if len(body) > MAX_TEXT:
        body = body[:MAX_TEXT] + "…"
    msg: dict[str, Any] = {"type": "text", "text": body}
    if quick_reply:
        msg["quickReply"] = {"items": quick_reply}
    return msg


def postback_item(label: str, data: str, display: str | None = None) -> dict[str, Any]:
    # ラベルは 20 文字まで (LINE の制限)
    action: dict[str, Any] = {"type": "postback", "label": label[:20], "data": data}
    if display:
        action["displayText"] = display
    return {"type": "action", "action": action}
