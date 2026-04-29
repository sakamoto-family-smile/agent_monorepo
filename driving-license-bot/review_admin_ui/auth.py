"""IAP JWT 検証 + email allowlist。

Cloud Run 前段に HTTPS LB + IAP を置き、IAP が `X-Goog-IAP-JWT-Assertion`
ヘッダで JWT を渡す。本モジュールはこれを Google 公開鍵で検証し、`email` を
取り出して allowlist チェックする。

ref: https://cloud.google.com/iap/docs/signed-headers-howto

開発時は `ADMIN_DEV_BYPASS=true` で検証をスキップ可能（dev email を返す）。
本番（Cloud Run）では必ず false にする。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from review_admin_ui.config import settings

logger = logging.getLogger(__name__)

IAP_JWT_HEADER = "X-Goog-IAP-JWT-Assertion"


@dataclass(frozen=True)
class AdminUser:
    """認証済み operator。FastAPI Depends 経由でハンドラに渡す。"""

    email: str
    sub: str = ""  # IAP の subject（一意 ID）


def _allowed_email_set() -> frozenset[str]:
    raw = settings.allowed_emails
    if not raw:
        return frozenset()
    return frozenset(e.strip().lower() for e in raw.split(",") if e.strip())


def _verify_iap_jwt(token: str) -> tuple[str, str]:
    """IAP JWT を検証し (email, sub) を返す。

    google-auth の `id_token.verify_token` を IAP issuer 用に呼ぶ。
    署名失敗 / audience 不一致は ValueError を上げるので呼び出し側で 401 にする。
    """
    try:
        from google.auth.transport import requests as g_requests
        from google.oauth2 import id_token
    except ImportError as exc:  # pragma: no cover — google-auth 未導入時
        raise RuntimeError(
            "google-auth is required (`uv sync` で再インストール)"
        ) from exc

    if not settings.iap_audience:
        raise ValueError("ADMIN_IAP_AUDIENCE is not configured")

    request = g_requests.Request()
    decoded = id_token.verify_token(
        token,
        request=request,
        audience=settings.iap_audience,
        certs_url="https://www.gstatic.com/iap/verify/public_key",
    )
    iss = decoded.get("iss", "")
    if iss != "https://cloud.google.com/iap":
        raise ValueError(f"unexpected issuer: {iss}")
    email = decoded.get("email", "")
    sub = decoded.get("sub", "")
    if not email:
        raise ValueError("email claim missing")
    return email, sub


async def require_admin(request: Request) -> AdminUser:
    """FastAPI Depends 用のガード。

    - dev_bypass=true → 即 dev email
    - 本番 → IAP header 必須、allowlist チェック
    """
    if settings.dev_bypass:
        logger.warning(
            "ADMIN_DEV_BYPASS=true: skipping IAP verification (dev only)"
        )
        return AdminUser(email=settings.dev_bypass_email)

    token = request.headers.get(IAP_JWT_HEADER)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing IAP JWT header",
        )

    try:
        email, sub = _verify_iap_jwt(token)
    except Exception as exc:  # noqa: BLE001 — JWT 失敗は多岐
        logger.warning("IAP JWT verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid IAP JWT",
        ) from exc

    allowed = _allowed_email_set()
    if not allowed:
        # allowlist 未設定の本番は **必ず拒否**（fail-closed）
        logger.error(
            "ADMIN_ALLOWED_EMAILS is empty in non-bypass mode → denying %s",
            email,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="allowlist not configured",
        )
    if email.lower() not in allowed:
        logger.info("denied: email %s not in allowlist", email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="email not allowed",
        )
    return AdminUser(email=email, sub=sub)


__all__ = ["AdminUser", "IAP_JWT_HEADER", "require_admin"]
