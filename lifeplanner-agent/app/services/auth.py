"""
Phase 1 用の認証スタブ。

- リクエストヘッダ `X-Household-ID` があればそれを使用
- 無ければ `DEV_HOUSEHOLD_ID` 環境変数（ローカル開発のデフォルト家計ID）
- 本番環境（APP_ENV=production）ではヘッダ必須、無ければ 401

Phase 3 で Firebase Auth + LINE Login に置き換える。
"""

from __future__ import annotations

import os

from fastapi import Header, HTTPException, status


async def get_household_id(
    x_household_id: str | None = Header(default=None, alias="X-Household-ID"),
) -> str:
    if x_household_id:
        return x_household_id

    # os.environ を直接参照する。Settings クラスのキャッシュを避けるため
    # テスト時に monkeypatch した値が即座に反映される。
    if os.environ.get("APP_ENV", "local") != "local":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Household-ID header is required",
        )

    return os.environ.get("DEV_HOUSEHOLD_ID", "dev-household-00000000")
