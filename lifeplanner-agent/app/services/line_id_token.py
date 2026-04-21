"""LINE ID Token の検証。

LIFF アプリから送られる ID トークンを LINE の `POST /oauth2/v2.1/verify` で検証する。
JWT を自前で verify する代わりにこの endpoint を使うことで、JWKS キャッシュや
署名アルゴリズムのコーナーケースを LINE 側に任せる。

参考: https://developers.line.biz/en/reference/line-login/#verify-id-token
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)


LINE_VERIFY_URL = "https://api.line.me/oauth2/v2.1/verify"


class IdTokenVerifierError(Exception):
    """ID トークンの検証に失敗した時に投げる。"""


@dataclass(frozen=True)
class VerifiedIdToken:
    sub: str  # LINE userId
    name: str | None
    email: str | None
    aud: str
    iss: str
    exp: int


class IdTokenVerifier(Protocol):
    async def verify(self, *, id_token: str, client_id: str) -> VerifiedIdToken: ...


class LineIdTokenVerifier:
    """LINE の verify endpoint を叩く本番実装。

    httpx の AsyncClient を注入できるようにしておくとテストで差し替え可能。
    """

    def __init__(self, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._http = http_client

    async def verify(self, *, id_token: str, client_id: str) -> VerifiedIdToken:
        if not id_token:
            raise IdTokenVerifierError("id_token is empty")
        if not client_id:
            raise IdTokenVerifierError("client_id (LINE Login channel ID) is empty")

        async def _do(client: httpx.AsyncClient) -> httpx.Response:
            return await client.post(
                LINE_VERIFY_URL,
                data={"id_token": id_token, "client_id": client_id},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10.0,
            )

        try:
            if self._http is not None:
                resp = await _do(self._http)
            else:
                async with httpx.AsyncClient() as client:
                    resp = await _do(client)
        except httpx.HTTPError as e:
            raise IdTokenVerifierError(f"network error: {e}") from e

        if resp.status_code != 200:
            # LINE は 400 に `error` / `error_description` を返す
            detail = resp.text
            raise IdTokenVerifierError(
                f"verify failed (HTTP {resp.status_code}): {detail}"
            )

        try:
            body = resp.json()
        except ValueError as e:
            raise IdTokenVerifierError(f"non-JSON response: {resp.text!r}") from e

        sub = body.get("sub")
        aud = body.get("aud")
        iss = body.get("iss")
        exp = body.get("exp")
        if not sub or not aud or not iss or exp is None:
            raise IdTokenVerifierError(f"missing required claims: {body}")

        return VerifiedIdToken(
            sub=str(sub),
            name=body.get("name"),
            email=body.get("email"),
            aud=str(aud),
            iss=str(iss),
            exp=int(exp),
        )


# ---------------------------------------------------------------------------
# DI
# ---------------------------------------------------------------------------

_default_verifier: IdTokenVerifier | None = None


def get_id_token_verifier() -> IdTokenVerifier:
    global _default_verifier
    if _default_verifier is None:
        _default_verifier = LineIdTokenVerifier()
    return _default_verifier


def set_id_token_verifier(verifier: IdTokenVerifier | None) -> None:
    """テスト用 setter。None で既定にリセット。"""
    global _default_verifier
    _default_verifier = verifier
