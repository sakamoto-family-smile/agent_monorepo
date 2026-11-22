"""共通の fixture: 一時ディレクトリの golf.db・偽の LINE API・時計・署名つきの webhook 送信。"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.config import Paths, Settings
from app.deps import Deps
from app.line.api import Download, LineApiError
from app.line.events import signature
from app.main import build_worker, close_deps, create_app, open_deps

SECRET = "test-channel-secret"
ME = "U" + "a" * 32
STRANGER = "U" + "b" * 32
# 2026-11-22 10:00 JST
START = datetime(2026, 11, 22, 1, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, now: datetime = START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


@dataclass
class FakeLine:
    replies: list[tuple[str, list[dict[str, Any]]]] = field(default_factory=list)
    pushes: list[tuple[str, list[dict[str, Any]], str]] = field(default_factory=list)
    transcoding: dict[str, list[str]] = field(default_factory=dict)
    contents: dict[str, tuple[bytes, str]] = field(default_factory=dict)
    download_errors: dict[str, LineApiError] = field(default_factory=dict)

    async def reply(self, reply_token: str, messages: list[dict[str, Any]]) -> None:
        self.replies.append((reply_token, messages))

    async def push(self, to: str, messages: list[dict[str, Any]], retry_key: str) -> None:
        self.pushes.append((to, messages, retry_key))

    async def transcoding_status(self, message_id: str) -> str:
        states = self.transcoding.get(message_id, ["succeeded"])
        return states.pop(0) if len(states) > 1 else states[0]

    async def download(self, message_id: str, dest: Path) -> Download:
        if message_id in self.download_errors:
            raise self.download_errors[message_id]
        data, content_type = self.contents[message_id]
        dest.write_bytes(data)
        return Download(content_type=content_type, size_bytes=len(data))

    def reply_texts(self) -> list[str]:
        return [m["text"] for _, msgs in self.replies for m in msgs if m["type"] == "text"]


@dataclass
class Env:
    deps: Deps
    line: FakeLine
    clock: FakeClock
    client: httpx.AsyncClient
    _seq: int = 0

    def next_id(self) -> str:
        self._seq += 1
        return f"01JTEST{self._seq:019d}"

    def event(self, kind: str = "message", user: str = ME, **body: Any) -> dict[str, Any]:
        eid = body.pop("webhook_event_id", None) or self.next_id()
        ev: dict[str, Any] = {
            "type": kind,
            "webhookEventId": eid,
            "timestamp": int(self.clock().timestamp() * 1000),
            "mode": "active",
            "source": {"type": "user", "userId": user},
            "replyToken": f"rt-{eid}",
            "deliveryContext": {"isRedelivery": body.pop("redelivery", False)},
        }
        ev.update(body)
        return ev

    def text_event(self, text: str, **kw: Any) -> dict[str, Any]:
        mid = kw.pop("message_id", None) or self.next_id()
        return self.event(message={"type": "text", "id": mid, "text": text}, **kw)

    def media_event(self, kind: str, message_id: str, **kw: Any) -> dict[str, Any]:
        message: dict[str, Any] = {"type": kind, "id": message_id, "contentProvider": {"type": "line"}}
        if kind == "video":
            message["duration"] = 4200
        return self.event(message=message, **kw)

    def postback_event(self, data: str, **kw: Any) -> dict[str, Any]:
        return self.event("postback", postback={"data": data}, **kw)

    async def post(self, *events: dict[str, Any], sign: str | None = None) -> httpx.Response:
        body = json.dumps({"destination": "Uxxx", "events": list(events)}).encode()
        sig = sign if sign is not None else signature(body, SECRET)
        return await self.client.post(
            "/api/line/webhook", content=body, headers={"X-Line-Signature": sig}
        )

    async def send_text(self, text: str, **kw: Any) -> str:
        """テキストを送り、返ってきた reply の本文 (1 件目) を返す。"""
        before = len(self.line.replies)
        res = await self.post(self.text_event(text, **kw))
        assert res.status_code == 200
        new = self.line.replies[before:]
        return new[0][1][0]["text"] if new else ""

    async def run_jobs(self) -> int:
        return await build_worker(self.deps).run_once()

    async def scalar(self, sql: str, **params: Any) -> Any:
        import sqlalchemy as sa

        async with self.deps.engine.connect() as conn:
            return (await conn.execute(sa.text(sql), params)).scalar()

    async def rows(self, sql: str, **params: Any) -> list[Any]:
        import sqlalchemy as sa

        async with self.deps.engine.connect() as conn:
            return list((await conn.execute(sa.text(sql), params)).mappings().all())


def make_settings(root: Path, **overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "app_env": "test",
        "paths": Paths(root / "data"),
        "line_channel_secret": SECRET,
        "line_channel_access_token": "test-token",
        "allowed_user_ids": frozenset({ME}),
        "tz": ZoneInfo("Asia/Tokyo"),
    }
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
async def env(tmp_path: Path) -> AsyncIterator[Env]:
    settings = make_settings(tmp_path)
    line = FakeLine()
    clock = FakeClock()
    deps = await open_deps(settings, line, clock)
    app = create_app(settings, line, clock)
    # lifespan (ワーカーの常駐) は動かさず、テストからジョブを 1 回ずつ動かす
    app.state.deps = deps
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield Env(deps=deps, line=line, clock=clock, client=client)
    await close_deps(deps)
