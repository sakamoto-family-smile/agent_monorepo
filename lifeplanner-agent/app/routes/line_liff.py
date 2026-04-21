"""LIFF (LINE Front-end Framework) 連携ルート。

エンドポイント:
  - `GET /liff/link.html` — LIFF ページ配信。フロントで `liff.getIDToken()` を呼び、
    `/api/line/liff-login` に POST する
  - `POST /api/line/liff-login` — ID トークンを LINE verify API で検証し、
    LINE userId を世帯に紐付ける (未連携なら自動作成)

設計:
  - LIFF_ID / LINE_LOGIN_CHANNEL_ID 未設定時は 503
  - JWT の自前検証は避け、LINE の verify endpoint にまかせる (`services/line_id_token.py`)
"""

from __future__ import annotations

import logging
import uuid

from config import settings
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from repositories.household import ensure_household, get_household
from repositories.line_link import create_link, get_link
from services.database import get_session_dep
from services.line_id_token import (
    IdTokenVerifier,
    IdTokenVerifierError,
    get_id_token_verifier,
)
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# 二つの router を module スコープで公開する (main で両方 include する)
liff_page_router = APIRouter(prefix="/liff", tags=["liff"])
liff_api_router = APIRouter(prefix="/api/line", tags=["liff"])


# ---------------------------------------------------------------------------
# LIFF ページ (静的 HTML)
# ---------------------------------------------------------------------------


def _liff_page_html(liff_id: str) -> str:
    """最小の LIFF ページ。LIFF ID 以外はユーザー入力由来を埋め込まないため安全。"""
    # `<` / `>` を含み得るのは liff_id のみ。これは管理者設定の env 値で
    # 英数と hyphen のみ想定だが念のため最低限エスケープする。
    safe_id = (
        liff_id.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;").replace("'", "&#39;")
    )
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>ライフプランナー LIFF 連携</title>
  <script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
  <style>
    body {{ font-family: system-ui, sans-serif; padding: 2rem; line-height: 1.6; }}
    .ok {{ color: #0a7f2e; }}
    .err {{ color: #b0282c; }}
    code {{ background: #f3f4f6; padding: 0.1rem 0.3rem; border-radius: 3px; }}
  </style>
</head>
<body>
  <h1>ライフプランナー 連携</h1>
  <p id="status">接続中…</p>
  <script>
  (async () => {{
    const status = document.getElementById("status");
    try {{
      await liff.init({{ liffId: "{safe_id}" }});
      if (!liff.isLoggedIn()) {{
        liff.login();
        return;
      }}
      const idToken = liff.getIDToken();
      if (!idToken) {{
        status.innerHTML = '<span class="err">ID token が取得できませんでした。LIFF 設定で "profile" と "openid" スコープを有効にしてください。</span>';
        return;
      }}
      const url = new URL(window.location.href);
      const householdParam = url.searchParams.get("household_id") || null;
      const res = await fetch("/api/line/liff-login", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ id_token: idToken, household_id: householdParam }}),
      }});
      const data = await res.json();
      if (!res.ok) {{
        status.innerHTML = '<span class="err">連携に失敗しました: ' + (data.detail || res.status) + '</span>';
        return;
      }}
      const msg = data.created
        ? "新しい世帯を作成して連携しました"
        : "既存の世帯に参加しました";
      status.innerHTML = '<span class="ok">' + msg + '</span>: <code>' + data.household_id + '</code>';
    }} catch (err) {{
      status.innerHTML = '<span class="err">エラー: ' + err.message + '</span>';
    }}
  }})();
  </script>
</body>
</html>
"""


@liff_page_router.get("/link.html", response_class=HTMLResponse)
async def liff_link_page() -> HTMLResponse:
    if not settings.line_liff_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LIFF_ID is not configured",
        )
    return HTMLResponse(content=_liff_page_html(settings.line_liff_id))


# ---------------------------------------------------------------------------
# LIFF login API
# ---------------------------------------------------------------------------


class LiffLoginIn(BaseModel):
    id_token: str = Field(..., min_length=10, max_length=4096)
    # 任意: 既存の特定世帯に紐付けたい場合に指定する。
    # 指定しなければ、未連携ユーザーには新規世帯を自動作成する。
    household_id: str | None = Field(default=None, max_length=64)


class LiffLoginOut(BaseModel):
    line_user_id: str
    household_id: str
    created: bool  # True = 新規世帯作成 / False = 既存世帯への紐付け (または既に連携済)
    already_linked: bool  # True = 既に同じ世帯に紐付いていた


def _new_household_id() -> str:
    return f"line-{uuid.uuid4().hex[:20]}"


@liff_api_router.post("/liff-login", response_model=LiffLoginOut)
async def liff_login(
    payload: LiffLoginIn,
    session: AsyncSession = Depends(get_session_dep),
    verifier: IdTokenVerifier = Depends(get_id_token_verifier),
) -> LiffLoginOut:
    if not settings.line_liff_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LIFF is not configured (LIFF_ID missing)",
        )
    if not settings.line_login_channel_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LINE_LOGIN_CHANNEL_ID is not configured",
        )

    try:
        verified = await verifier.verify(
            id_token=payload.id_token,
            client_id=settings.line_login_channel_id,
        )
    except IdTokenVerifierError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"ID token verification failed: {e}",
        ) from e

    line_user_id = verified.sub
    if not line_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ID token did not include a sub claim",
        )

    from instrumentation import emit_business

    existing_link = await get_link(session, line_user_id)
    if existing_link is not None:
        # すでに紐付いている: 要求があってかつ異なる世帯なら 409、同じなら冪等に OK
        if payload.household_id and payload.household_id != existing_link.household_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"LINE user already linked to household {existing_link.household_id}"
                ),
            )
        emit_business(
            domain="line",
            action="liff_login",
            resource_type="household",
            resource_id=existing_link.household_id,
            attributes={"created": False, "already_linked": True},
            user_id=existing_link.household_id,
        )
        return LiffLoginOut(
            line_user_id=line_user_id,
            household_id=existing_link.household_id,
            created=False,
            already_linked=True,
        )

    if payload.household_id:
        # 明示指定された世帯に参加する
        existing_household = await get_household(session, payload.household_id)
        if existing_household is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Household {payload.household_id} not found",
            )
        await create_link(
            session, line_user_id=line_user_id, household_id=payload.household_id
        )
        await session.commit()
        emit_business(
            domain="line",
            action="liff_login",
            resource_type="household",
            resource_id=payload.household_id,
            attributes={"created": False, "already_linked": False},
            user_id=payload.household_id,
        )
        return LiffLoginOut(
            line_user_id=line_user_id,
            household_id=payload.household_id,
            created=False,
            already_linked=False,
        )

    # 未指定: 新規世帯を作って自動連携
    new_id = _new_household_id()
    await ensure_household(session, new_id, name=f"LINE {new_id}")
    await create_link(session, line_user_id=line_user_id, household_id=new_id)
    await session.commit()
    emit_business(
        domain="line",
        action="liff_login",
        resource_type="household",
        resource_id=new_id,
        attributes={"created": True, "already_linked": False},
        user_id=new_id,
    )
    return LiffLoginOut(
        line_user_id=line_user_id,
        household_id=new_id,
        created=True,
        already_linked=False,
    )
