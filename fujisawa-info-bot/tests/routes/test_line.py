"""LINE webhook route のテスト (Phase 2: LangGraph 統合)。

実 LINE SDK の `WebhookParser` を使い、 LINE 公式仕様の JSON + 正規署名で
end-to-end に動作確認する。 `reply_text` は `LineBotClient` のサブクラスで
capture する。 graph deps は MockLLM + InMemoryStore + MockEmbedding で固定する。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from fujisawa_platform.knowledge_base import (
    InMemoryStore,
    MockEmbeddingClient,
    PageDocument,
)
from llm_client import MockLLMClient

from app import line_client as line_client_module
from app.graph import GraphDependencies
from app.line_client import LineBotClient, reset_line_bot_client
from app.main import app

_SECRET = "test-channel-secret"
_TOKEN = "test-channel-access-token"
_FIXED_LLM_REPLY = "鵠沼地区は燃えるゴミが月曜日・木曜日です。"


def _sign(body: bytes, secret: str = _SECRET) -> str:
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(mac).decode("utf-8")


def _make_text_event(*, text: str, reply_token: str = "reply-1") -> dict:
    return {
        "type": "message",
        "replyToken": reply_token,
        "source": {"type": "user", "userId": "U_test"},
        "timestamp": 1700000000000,
        "mode": "active",
        "webhookEventId": "evt-1",
        "deliveryContext": {"isRedelivery": False},
        "message": {
            "type": "text",
            "id": "msg-1",
            "quoteToken": "qt-1",
            "text": text,
        },
    }


class _CapturingClient(LineBotClient):
    """`reply_text` をモックして送信内容を capture する。"""

    def __init__(self, *, channel_secret: str, channel_access_token: str) -> None:
        super().__init__(channel_secret=channel_secret, channel_access_token=channel_access_token)
        self.replies: list[tuple[str, list[str]]] = []

    def reply_text(self, reply_token: str, messages: list[str]) -> None:  # type: ignore[override]
        self.replies.append((reply_token, messages))


def _build_test_deps() -> GraphDependencies:
    """deterministic な graph 依存セットを返す。

    MockLLM は category_routing にも RAG 整形にも同じ固定文を返すが、
    intent.py は JSON parse 失敗時 fallback で rag に分類するので
    `_FIXED_LLM_REPLY` (JSON ではない) を返してもテストは成立する。
    """
    embedding = MockEmbeddingClient(dimension=64)
    store = InMemoryStore(embedding_dim=64)
    return GraphDependencies(
        llm=MockLLMClient(fixed_reply=_FIXED_LLM_REPLY),
        embedding=embedding,
        store=store,
        top_k=3,
    )


@pytest.fixture
def line_client_capturing(monkeypatch: pytest.MonkeyPatch) -> _CapturingClient:
    """settings に test 値を流し、 LineBotClient を CapturingClient に差し替える。"""
    monkeypatch.setattr(line_client_module.settings, "line_channel_secret", _SECRET, raising=False)
    monkeypatch.setattr(
        line_client_module.settings, "line_channel_access_token", _TOKEN, raising=False
    )
    reset_line_bot_client()
    client = _CapturingClient(channel_secret=_SECRET, channel_access_token=_TOKEN)
    monkeypatch.setattr(line_client_module, "_client_singleton", client, raising=False)
    yield client
    reset_line_bot_client()


@pytest.fixture
def client_with_deps(line_client_capturing: _CapturingClient):
    """TestClient + lifespan で起動した state.graph_deps を test 用に上書き。"""
    with TestClient(app) as tc:
        tc.app.state.graph_deps = _build_test_deps()
        yield tc, line_client_capturing


@pytest.fixture
def client_no_line(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """LINE_* 未設定状態の TestClient。"""
    monkeypatch.setattr(line_client_module.settings, "line_channel_secret", "", raising=False)
    monkeypatch.setattr(
        line_client_module.settings, "line_channel_access_token", "", raising=False
    )
    reset_line_bot_client()
    with TestClient(app) as tc:
        yield tc
    reset_line_bot_client()


class TestWebhook:
    def test_returns_503_when_line_not_configured(self, client_no_line: TestClient) -> None:
        body = json.dumps({"events": []}).encode("utf-8")
        resp = client_no_line.post(
            "/webhook",
            content=body,
            headers={
                "X-Line-Signature": _sign(body),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 503

    def test_returns_401_on_invalid_signature(self, client_with_deps) -> None:
        tc, capturing = client_with_deps
        body = json.dumps({"events": []}).encode("utf-8")
        resp = tc.post(
            "/webhook",
            content=body,
            headers={
                "X-Line-Signature": "obviously-wrong",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401
        assert capturing.replies == []

    def test_replies_with_rag_no_hit_when_store_empty(self, client_with_deps) -> None:
        """store が空 → RAG ノードが固定文 (該当ページ無し) を返す。"""
        tc, capturing = client_with_deps
        payload = {"destination": "U_dest", "events": [_make_text_event(text="ゴミの日教えて")]}
        body = json.dumps(payload).encode("utf-8")
        resp = tc.post(
            "/webhook",
            content=body,
            headers={
                "X-Line-Signature": _sign(body),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert len(capturing.replies) == 1
        reply_token, messages = capturing.replies[0]
        assert reply_token == "reply-1"
        assert len(messages) == 1
        assert "公式 HP から該当する情報が見つかりませんでした" in messages[0]

    def test_replies_with_rag_answer_when_store_has_match(self, client_with_deps) -> None:
        """store に該当ページを入れると LLM 整形 + 出典フッタが付く。"""
        tc, capturing = client_with_deps
        # seed
        deps: GraphDependencies = tc.app.state.graph_deps
        page = PageDocument(
            page_id="p1",
            url="https://www.city.fujisawa.kanagawa.jp/test1",
            title="ゴミ収集カレンダー",
            content="鵠沼地区は燃えるゴミが月曜・木曜です。",
            embedding=deps.embedding.embed("ゴミ"),
            category="garbage",
            fetched_at=datetime.now(UTC),
        )
        import asyncio

        asyncio.run(deps.store.upsert_page(page))

        payload = {"destination": "U_dest", "events": [_make_text_event(text="ゴミの日")]}
        body = json.dumps(payload).encode("utf-8")
        resp = tc.post(
            "/webhook",
            content=body,
            headers={
                "X-Line-Signature": _sign(body),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert len(capturing.replies) == 1
        _, messages = capturing.replies[0]
        assert _FIXED_LLM_REPLY in messages[0]
        assert "https://www.city.fujisawa.kanagawa.jp/test1" in messages[0]
        assert messages[0].startswith(_FIXED_LLM_REPLY)
        assert "出典:" in messages[0]

    def test_ignores_non_text_message(self, client_with_deps) -> None:
        tc, capturing = client_with_deps
        sticker_event = {
            "type": "message",
            "replyToken": "reply-x",
            "source": {"type": "user", "userId": "U_test"},
            "timestamp": 1700000000000,
            "mode": "active",
            "webhookEventId": "evt-2",
            "deliveryContext": {"isRedelivery": False},
            "message": {
                "type": "sticker",
                "id": "msg-2",
                "quoteToken": "qt-2",
                "packageId": "446",
                "stickerId": "1988",
                "stickerResourceType": "STATIC",
                "keywords": [],
            },
        }
        body = json.dumps({"events": [sticker_event]}).encode("utf-8")
        resp = tc.post(
            "/webhook",
            content=body,
            headers={
                "X-Line-Signature": _sign(body),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert capturing.replies == []

    def test_handles_multiple_text_events_in_single_webhook(self, client_with_deps) -> None:
        tc, capturing = client_with_deps
        events = [
            _make_text_event(text="hello", reply_token="rt-a"),
            _make_text_event(text="world", reply_token="rt-b"),
        ]
        body = json.dumps({"events": events}).encode("utf-8")
        resp = tc.post(
            "/webhook",
            content=body,
            headers={
                "X-Line-Signature": _sign(body),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert len(capturing.replies) == 2
        tokens = [t for t, _ in capturing.replies]
        assert tokens == ["rt-a", "rt-b"]
