"""LIFF 連携 (/liff/link.html, /api/line/liff-login) の統合テスト。

ID トークン検証は LINE の API を叩かず、`StubIdTokenVerifier` を差し替えて行う。
"""

from __future__ import annotations

import time

import pytest
from services.line_id_token import (
    IdTokenVerifier,
    IdTokenVerifierError,
    VerifiedIdToken,
    set_id_token_verifier,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Stub verifier
# ---------------------------------------------------------------------------


class StubIdTokenVerifier:
    def __init__(
        self,
        *,
        sub: str = "U_stub_line_user",
        fail: bool = False,
    ) -> None:
        self.sub = sub
        self.fail = fail
        self.called_with: dict = {}

    async def verify(self, *, id_token: str, client_id: str) -> VerifiedIdToken:
        self.called_with = {"id_token": id_token, "client_id": client_id}
        if self.fail:
            raise IdTokenVerifierError("stub: bad token")
        return VerifiedIdToken(
            sub=self.sub,
            name=None,
            email=None,
            aud=client_id,
            iss="https://access.line.me",
            exp=int(time.time()) + 3600,
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def liff_env(client, monkeypatch):
    """LIFF_ID / LINE_LOGIN_CHANNEL_ID を有効にした client + スタブ verifier。

    `client` fixture が config を reload する一方で、ルート (`routes.line_liff`) は
    sys.modules キャッシュから再ロードされないため、ルート側が握る settings
    インスタンス (= `routes.line_liff.settings`) に対して直接属性を差し替える。
    """
    from routes import line_liff as liff_route

    monkeypatch.setattr(liff_route.settings, "line_liff_id", "1234567890-abcdefgh")
    monkeypatch.setattr(
        liff_route.settings, "line_login_channel_id", "1234567890"
    )

    verifier: IdTokenVerifier = StubIdTokenVerifier()
    set_id_token_verifier(verifier)
    yield client, verifier
    set_id_token_verifier(None)


# ---------------------------------------------------------------------------
# LIFF HTML page
# ---------------------------------------------------------------------------


async def test_liff_page_returns_503_when_liff_id_missing(client):
    from config import settings

    # 既定値は空文字 (未設定)
    assert settings.line_liff_id == ""
    r = await client.get("/liff/link.html")
    assert r.status_code == 503


async def test_liff_page_renders_html_with_liff_id(liff_env):
    c, _ = liff_env
    r = await c.get("/liff/link.html")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    assert "liff.init" in body
    assert "1234567890-abcdefgh" in body
    # SDK 読み込み
    assert "static.line-scdn.net/liff/edge/2/sdk.js" in body


async def test_liff_page_escapes_dangerous_chars_in_liff_id(client, monkeypatch):
    from routes import line_liff as liff_route

    monkeypatch.setattr(
        liff_route.settings, "line_liff_id", '"><script>alert(1)</script>'
    )
    r = await client.get("/liff/link.html")
    assert r.status_code == 200
    # 生のスクリプトタグは出てはいけない (<script>alert のペイロード)
    assert "<script>alert(1)</script>" not in r.text
    # エスケープ済みのエンティティは含まれるはず
    assert "&lt;script&gt;" in r.text


# ---------------------------------------------------------------------------
# /api/line/liff-login
# ---------------------------------------------------------------------------


async def test_liff_login_returns_503_when_liff_id_missing(client):
    r = await client.post("/api/line/liff-login", json={"id_token": "x" * 30})
    assert r.status_code == 503


async def test_liff_login_returns_503_when_login_channel_missing(client, monkeypatch):
    from routes import line_liff as liff_route

    monkeypatch.setattr(liff_route.settings, "line_liff_id", "some-liff")
    # line_login_channel_id は設定しない
    r = await client.post("/api/line/liff-login", json={"id_token": "x" * 30})
    assert r.status_code == 503


async def test_liff_login_returns_401_when_verifier_raises(client, monkeypatch):
    from routes import line_liff as liff_route

    monkeypatch.setattr(liff_route.settings, "line_liff_id", "some-liff")
    monkeypatch.setattr(liff_route.settings, "line_login_channel_id", "1234567890")
    set_id_token_verifier(StubIdTokenVerifier(fail=True))
    try:
        r = await client.post("/api/line/liff-login", json={"id_token": "x" * 30})
        assert r.status_code == 401
        assert "ID token verification failed" in r.json()["detail"]
    finally:
        set_id_token_verifier(None)


async def test_liff_login_auto_creates_household_when_no_param(liff_env):
    c, verifier = liff_env
    r = await c.post("/api/line/liff-login", json={"id_token": "dummy-token-xxxxx"})
    assert r.status_code == 200
    body = r.json()
    assert body["line_user_id"] == "U_stub_line_user"
    assert body["household_id"].startswith("line-")
    assert body["created"] is True
    assert body["already_linked"] is False
    # verifier に正しい client_id が渡ったこと
    assert verifier.called_with["client_id"] == "1234567890"


async def test_liff_login_links_to_existing_household_when_param_given(liff_env):
    c, _ = liff_env
    # test-household を `/api/scenarios` で作成
    r = await c.post(
        "/api/scenarios",
        json={
            "name": "Base",
            "description": "",
            "primary_salary": "6000000",
            "start_year": 2026,
            "horizon_years": 30,
        },
    )
    assert r.status_code == 201

    r = await c.post(
        "/api/line/liff-login",
        json={"id_token": "dummy-token-xxxxx", "household_id": "test-household"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["household_id"] == "test-household"
    assert body["created"] is False
    assert body["already_linked"] is False


async def test_liff_login_404_when_specified_household_missing(liff_env):
    c, _ = liff_env
    r = await c.post(
        "/api/line/liff-login",
        json={"id_token": "dummy-token-xxxxx", "household_id": "does-not-exist"},
    )
    assert r.status_code == 404


async def test_liff_login_idempotent_when_same_household(liff_env):
    c, _ = liff_env
    # 一度目: 自動作成
    r = await c.post("/api/line/liff-login", json={"id_token": "t" * 30})
    assert r.status_code == 200
    first_household = r.json()["household_id"]

    # 二度目: 同じユーザで同じ呼出 → 既存の紐付けを返すだけ
    r = await c.post("/api/line/liff-login", json={"id_token": "t" * 30})
    assert r.status_code == 200
    body = r.json()
    assert body["household_id"] == first_household
    assert body["created"] is False
    assert body["already_linked"] is True


async def test_liff_login_409_when_already_linked_to_different_household(liff_env):
    c, _ = liff_env

    # 自動作成で一つ目の世帯に紐付け
    r1 = await c.post("/api/line/liff-login", json={"id_token": "t" * 30})
    assert r1.status_code == 200

    # 別の世帯を用意 (API 経由)
    r = await c.post(
        "/api/scenarios",
        headers={"X-Household-ID": "other-household"},
        json={
            "name": "Other",
            "description": "",
            "primary_salary": "6000000",
            "start_year": 2026,
            "horizon_years": 30,
        },
    )
    assert r.status_code == 201

    # 別世帯への post は 409
    r2 = await c.post(
        "/api/line/liff-login",
        json={"id_token": "t" * 30, "household_id": "other-household"},
    )
    assert r2.status_code == 409


# ---------------------------------------------------------------------------
# LineIdTokenVerifier (low-level, network stubbed)
# ---------------------------------------------------------------------------


async def test_line_id_token_verifier_parses_ok_response(monkeypatch):
    """LINE の verify endpoint が 200 で JSON を返したら VerifiedIdToken を生成できる。"""
    import httpx
    from services.line_id_token import LineIdTokenVerifier

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/oauth2/v2.1/verify"
        assert request.method == "POST"
        return httpx.Response(
            200,
            json={
                "iss": "https://access.line.me",
                "sub": "Uline123",
                "aud": "1234567890",
                "exp": int(time.time()) + 3600,
                "name": "テスト太郎",
                "email": "test@example.com",
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://api.line.me"
    ) as http:
        verifier = LineIdTokenVerifier(http_client=http)
        # MockTransport は base_url で解決するので、呼出 URL を差し替える必要あり
        monkeypatch.setattr(
            "services.line_id_token.LINE_VERIFY_URL",
            "https://api.line.me/oauth2/v2.1/verify",
        )
        result = await verifier.verify(id_token="token", client_id="1234567890")

    assert result.sub == "Uline123"
    assert result.aud == "1234567890"


async def test_line_id_token_verifier_raises_on_400():
    import httpx
    from services.line_id_token import LineIdTokenVerifier

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": "invalid_request", "error_description": "expired"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        verifier = LineIdTokenVerifier(http_client=http)
        with pytest.raises(IdTokenVerifierError) as exc:
            await verifier.verify(id_token="bad", client_id="1234567890")

    assert "HTTP 400" in str(exc.value)


async def test_line_id_token_verifier_rejects_empty_inputs():
    from services.line_id_token import LineIdTokenVerifier

    verifier = LineIdTokenVerifier()
    with pytest.raises(IdTokenVerifierError):
        await verifier.verify(id_token="", client_id="x")
    with pytest.raises(IdTokenVerifierError):
        await verifier.verify(id_token="abc", client_id="")
