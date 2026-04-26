"""LINE Webhook のハンドラ層テスト。

- 未設定時 503
- 署名欠落時 401
- 許可リスト外ユーザは無視
- テキストコマンド → reply_text に summary
- FileMessage → ack + background import → push_text で完了
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import json
from dataclasses import dataclass, field

import pytest
from conftest import load_fixture
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# ヘルパ: LINE 風ペイロード + 署名生成
# ---------------------------------------------------------------------------


def _sign(body: bytes, secret: str) -> str:
    import base64

    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(mac).decode("utf-8")


def _text_event_body(user_id: str, text: str, reply_token: str = "rt1") -> bytes:
    payload = {
        "events": [
            {
                "type": "message",
                "timestamp": 1700000000,
                "source": {"type": "user", "userId": user_id},
                "replyToken": reply_token,
                "message": {"id": "m1", "type": "text", "text": text},
            }
        ]
    }
    return json.dumps(payload).encode("utf-8")


def _file_event_body(user_id: str, filename: str, file_size: int, message_id: str = "mfile1", reply_token: str = "rt2") -> bytes:
    payload = {
        "events": [
            {
                "type": "message",
                "timestamp": 1700000000,
                "source": {"type": "user", "userId": user_id},
                "replyToken": reply_token,
                "message": {
                    "id": message_id,
                    "type": "file",
                    "fileName": filename,
                    "fileSize": file_size,
                },
            }
        ]
    }
    return json.dumps(payload).encode("utf-8")


# ---------------------------------------------------------------------------
# スタブ LineBotClient
# ---------------------------------------------------------------------------


@dataclass
class StubLineClient:
    secret: str
    reply_messages: list[tuple[str, str]] = field(default_factory=list)
    push_messages: list[tuple[str, str]] = field(default_factory=list)
    fetched_content: bytes = b""
    fetch_calls: list[str] = field(default_factory=list)

    def parse_events(self, *, body: bytes, signature: str):
        # 実装は sdk を使わず自前のシンプルなパース
        from services.line_client import LineFileEvent, LineTextEvent

        expected = _sign(body, self.secret)
        if signature != expected:
            from services.line_client import InvalidSignatureError

            raise InvalidSignatureError("bad signature")

        data = json.loads(body)
        events = []
        for ev in data.get("events", []):
            if ev.get("type") != "message":
                continue
            user_id = ev["source"]["userId"]
            reply_token = ev.get("replyToken", "")
            msg = ev["message"]
            if msg["type"] == "text":
                events.append(
                    LineTextEvent(
                        event_type="text",
                        line_user_id=user_id,
                        reply_token=reply_token,
                        text=msg["text"],
                    )
                )
            elif msg["type"] == "file":
                events.append(
                    LineFileEvent(
                        event_type="file",
                        line_user_id=user_id,
                        reply_token=reply_token,
                        message_id=msg["id"],
                        filename=msg.get("fileName", ""),
                        file_size=int(msg.get("fileSize", 0)),
                    )
                )
        return events

    async def reply_text(self, *, reply_token: str, text: str) -> None:
        self.reply_messages.append((reply_token, text))

    async def push_text(self, *, to: str, text: str) -> None:
        self.push_messages.append((to, text))

    async def fetch_message_content(self, *, message_id: str) -> bytes:
        self.fetch_calls.append(message_id)
        return self.fetched_content

    async def close(self) -> None:
        return None


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "testsecret")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "testtoken")
    monkeypatch.setenv("FAMILY_USER_IDS", "UALLOWED1,UALLOWED2")
    monkeypatch.setenv("FAMILY_ID", "fam1")
    monkeypatch.setenv("DEFAULT_CHILD_ID", "default")
    monkeypatch.setenv("PIYOLOG_DB_PATH", str(tmp_path / "line.db"))
    monkeypatch.setenv("ANALYTICS_ENABLED", "false")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    monkeypatch.setenv("ANALYTICS_DATA_DIR", str(tmp_path / "analytics"))
    # reload config + instrumentation singletons
    import config as cfg
    importlib.reload(cfg)
    import instrumentation.setup as obs_setup
    importlib.reload(obs_setup)
    # main / routes もリロードして新 settings を拾わせる
    import routes.line as line_route
    importlib.reload(line_route)
    import main as main_mod
    importlib.reload(main_mod)
    return main_mod


@pytest.fixture
def stub(env):
    stub_client = StubLineClient(secret="testsecret")
    import services.line_client as lc
    lc.set_line_bot_client(stub_client)
    yield stub_client
    lc.set_line_bot_client(None)


@pytest.fixture
def client(env, stub):
    with TestClient(env.app) as c:
        yield c


# ---------------------------------------------------------------------------
# 503: LINE 未設定時
# ---------------------------------------------------------------------------


def test_503_when_line_unconfigured(monkeypatch, tmp_path):
    monkeypatch.delenv("LINE_CHANNEL_SECRET", raising=False)
    monkeypatch.delenv("LINE_CHANNEL_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("FAMILY_USER_IDS", "U1")
    monkeypatch.setenv("PIYOLOG_DB_PATH", str(tmp_path / "x.db"))
    monkeypatch.setenv("ANALYTICS_ENABLED", "false")
    monkeypatch.setenv("ANALYTICS_DATA_DIR", str(tmp_path / "analytics"))
    import config as cfg
    importlib.reload(cfg)
    import instrumentation.setup as obs_setup
    importlib.reload(obs_setup)
    import services.line_client as lc
    importlib.reload(lc)
    lc.set_line_bot_client(None)
    import routes.line as rl
    importlib.reload(rl)
    import main as main_mod
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as client:
        resp = client.post("/api/line/webhook", content=b"{}", headers={"X-Line-Signature": "x"})
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# 401: 署名欠落 / 不正
# ---------------------------------------------------------------------------


def test_401_when_signature_missing(client):
    resp = client.post("/api/line/webhook", content=b"{}")
    assert resp.status_code == 401


def test_401_when_signature_invalid(client):
    body = _text_event_body("UALLOWED1", "ヘルプ")
    resp = client.post(
        "/api/line/webhook",
        content=body,
        headers={"X-Line-Signature": "bogus"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# アクセス制御
# ---------------------------------------------------------------------------


def test_rejects_non_family_user_silently(client, stub):
    body = _text_event_body("UOUTSIDER", "ヘルプ")
    sig = _sign(body, "testsecret")
    resp = client.post(
        "/api/line/webhook", content=body, headers={"X-Line-Signature": sig}
    )
    assert resp.status_code == 200
    # 無視されたので reply は飛ばない
    assert stub.reply_messages == []


# ---------------------------------------------------------------------------
# B4 開通: bootstrap mode (FAMILY_USER_IDS 未設定 = 全員 silent + userId を WARN log)
# ---------------------------------------------------------------------------


def test_bootstrap_mode_logs_full_userid_when_family_user_ids_empty(
    monkeypatch, tmp_path, caplog
):
    """`FAMILY_USER_IDS=""` で deploy したとき、メッセージ受信で full userId を WARN log。"""
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "testsecret")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "testtoken")
    monkeypatch.setenv("FAMILY_USER_IDS", "")  # ← 開通用に空に
    monkeypatch.setenv("FAMILY_ID", "fam1")
    monkeypatch.setenv("DEFAULT_CHILD_ID", "default")
    monkeypatch.setenv("PIYOLOG_DB_PATH", str(tmp_path / "bootstrap.db"))
    monkeypatch.setenv("ANALYTICS_ENABLED", "false")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    monkeypatch.setenv("ANALYTICS_DATA_DIR", str(tmp_path / "analytics"))
    importlib.reload(__import__("config"))
    importlib.reload(__import__("instrumentation.setup", fromlist=["x"]))
    importlib.reload(__import__("routes.line", fromlist=["x"]))
    main_mod = importlib.reload(__import__("main"))

    stub_client = StubLineClient(secret="testsecret")
    import services.line_client as lc

    lc.set_line_bot_client(stub_client)

    body = _text_event_body("Uffffffffffffffffffffffffffffffff", "hi")
    sig = _sign(body, "testsecret")
    with TestClient(main_mod.app) as client, caplog.at_level("WARNING"):
        resp = client.post(
            "/api/line/webhook", content=body, headers={"X-Line-Signature": sig}
        )
    lc.set_line_bot_client(None)

    assert resp.status_code == 200
    # bootstrap log に full userId が出ている (家族の userId 取得用)
    bootstrap_logs = [r for r in caplog.records if "[bootstrap] FAMILY_USER_IDS unset" in r.message]
    assert bootstrap_logs, "expected bootstrap log when FAMILY_USER_IDS is empty"
    assert "Uffffffffffffffffffffffffffffffff" in bootstrap_logs[0].message
    # bootstrap mode では reply しない
    assert stub_client.reply_messages == []


# ---------------------------------------------------------------------------
# テキストコマンド
# ---------------------------------------------------------------------------


def test_help_command_returns_help_text(client, stub):
    body = _text_event_body("UALLOWED1", "ヘルプ")
    sig = _sign(body, "testsecret")
    resp = client.post(
        "/api/line/webhook", content=body, headers={"X-Line-Signature": sig}
    )
    assert resp.status_code == 200
    assert len(stub.reply_messages) == 1
    token, text = stub.reply_messages[0]
    assert token == "rt1"
    assert "ぴよログ分析" in text


def test_today_command_with_no_data_returns_empty_message(client, stub):
    body = _text_event_body("UALLOWED1", "今日")
    sig = _sign(body, "testsecret")
    resp = client.post(
        "/api/line/webhook", content=body, headers={"X-Line-Signature": sig}
    )
    assert resp.status_code == 200
    assert len(stub.reply_messages) == 1
    _, text = stub.reply_messages[0]
    assert "記録がありません" in text


# ---------------------------------------------------------------------------
# ファイル添付: ack + background import + push 完了通知
# ---------------------------------------------------------------------------


def test_file_message_triggers_ack_and_import(client, stub):
    raw = load_fixture("daily_sample.txt").encode("utf-8")
    stub.fetched_content = raw
    body = _file_event_body("UALLOWED1", "piyolog.txt", len(raw))
    sig = _sign(body, "testsecret")
    resp = client.post(
        "/api/line/webhook", content=body, headers={"X-Line-Signature": sig}
    )
    assert resp.status_code == 200
    # ack (reply) は必ず出ている
    assert len(stub.reply_messages) == 1
    _, ack_text = stub.reply_messages[0]
    assert "取り込みを開始" in ack_text

    # BackgroundTasks は TestClient 内で同期的に実行される
    assert len(stub.push_messages) == 1
    _, push_text = stub.push_messages[0]
    assert "取り込み完了" in push_text
    assert "16 件" in push_text


def test_file_message_duplicate_reports_skipped(client, stub):
    raw = load_fixture("daily_sample.txt").encode("utf-8")
    stub.fetched_content = raw
    body = _file_event_body("UALLOWED1", "p.txt", len(raw), message_id="m1")
    sig = _sign(body, "testsecret")
    client.post("/api/line/webhook", content=body, headers={"X-Line-Signature": sig})

    # 2 回目: 同じ内容 → duplicate
    body2 = _file_event_body("UALLOWED1", "p.txt", len(raw), message_id="m2", reply_token="rt3")
    sig2 = _sign(body2, "testsecret")
    client.post("/api/line/webhook", content=body2, headers={"X-Line-Signature": sig2})

    dup_push = [m for m in stub.push_messages if "取り込み済み" in m[1]]
    assert len(dup_push) == 1


def test_file_message_rejects_non_piyolog_content(client, stub):
    stub.fetched_content = b"hello world, not piyolog"
    body = _file_event_body("UALLOWED1", "x.txt", len(stub.fetched_content))
    sig = _sign(body, "testsecret")
    resp = client.post(
        "/api/line/webhook", content=body, headers={"X-Line-Signature": sig}
    )
    assert resp.status_code == 200
    # 失敗 push
    fail_push = [m for m in stub.push_messages if "失敗" in m[1]]
    assert len(fail_push) == 1


def test_end_to_end_import_then_summary(client, stub):
    """取り込み後にサマリクエリが結果を返すこと。"""
    raw = load_fixture("daily_sample.txt").encode("utf-8")
    stub.fetched_content = raw

    # Import
    body = _file_event_body("UALLOWED1", "d.txt", len(raw))
    sig = _sign(body, "testsecret")
    client.post("/api/line/webhook", content=body, headers={"X-Line-Signature": sig})

    # Summary — fixture 日付に合わせる必要があるので period コマンドで明示指定
    stub.reply_messages.clear()
    body = _text_event_body("UALLOWED1", "期間 2026-04-22 2026-04-22")
    sig = _sign(body, "testsecret")
    resp = client.post(
        "/api/line/webhook", content=body, headers={"X-Line-Signature": sig}
    )
    assert resp.status_code == 200
    _, text = stub.reply_messages[0]
    assert "260ml" in text
    assert "36.8°C" in text
