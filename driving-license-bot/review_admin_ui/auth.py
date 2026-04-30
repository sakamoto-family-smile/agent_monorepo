"""Google OAuth 2.0 + signed session cookie による認証。

Cloud Run direct IAP は個人 GCP project (組織所属なし) では OAuth client の
自動 provisioning が動かないため、App-level OAuth に切り替えた。

フロー:
    1. 未ログインで /login 以外にアクセス → /login にリダイレクト
    2. /login → Google OAuth consent screen にリダイレクト (Authlib)
    3. /auth/callback → ID token を取得・検証 → email allowlist チェック
       → 通れば session cookie に email を保存 → "/" にリダイレクト
    4. その後の request は session cookie で認証 (require_admin で判定)
    5. /logout で cookie をクリア

`ADMIN_DEV_BYPASS=true` で OAuth flow をスキップ（テスト・ローカル開発用）。
本番 (Cloud Run) では必ず false。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from fastapi.responses import RedirectResponse

from review_admin_ui.config import settings

logger = logging.getLogger(__name__)

SESSION_USER_KEY = "admin_user_email"


@dataclass(frozen=True)
class AdminUser:
    """認証済み operator。FastAPI Depends 経由でハンドラに渡す。"""

    email: str


def allowed_email_set() -> frozenset[str]:
    raw = settings.allowed_emails
    if not raw:
        return frozenset()
    return frozenset(e.strip().lower() for e in raw.split(",") if e.strip())


def is_email_allowed(email: str) -> bool:
    """allowlist 検証。空なら fail-closed (deny all)。"""
    allowed = allowed_email_set()
    if not allowed:
        return False
    return email.lower() in allowed


async def require_admin(request: Request) -> AdminUser:
    """FastAPI Depends 用のガード。

    - dev_bypass=true → 即 dev email
    - 本番 → session cookie 必須、未ログインなら /login にリダイレクト
    """
    if settings.dev_bypass:
        logger.warning("ADMIN_DEV_BYPASS=true: skipping OAuth (dev only)")
        return AdminUser(email=settings.dev_bypass_email)

    email = request.session.get(SESSION_USER_KEY)
    if not email:
        # 未ログイン: /login にリダイレクト。FastAPI の HTTPException は 4xx しか
        # 表現できないので Depends 経由で 303 を返すために custom exception を使う。
        raise _RedirectToLogin()

    if not is_email_allowed(email):
        # cookie に乗っていた email が allowlist から外れた場合（運用変更等）
        # session を消してから 403 を返す
        request.session.clear()
        logger.info("denied: session email %s no longer in allowlist", email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="email not allowed",
        )
    return AdminUser(email=email)


class _RedirectToLogin(Exception):
    """未ログイン時の signal exception。main.py の exception_handler で 303 に変換。"""

    pass


def install_redirect_handler(app) -> None:
    """FastAPI app に _RedirectToLogin → /login への 303 ハンドラを登録。

    main.py の create_app() から呼ぶ。
    """

    @app.exception_handler(_RedirectToLogin)
    async def _handler(request: Request, exc: _RedirectToLogin):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


__all__ = [
    "AdminUser",
    "SESSION_USER_KEY",
    "allowed_email_set",
    "install_redirect_handler",
    "is_email_allowed",
    "require_admin",
]
