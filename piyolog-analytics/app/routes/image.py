"""Phase 1.5: 一時画像配信 (`/api/line/image/{id}.png`)。

LINE の ImageMessage は public な HTTPS URL を要求する。アプリ内の `ImageStore`
(メモリ LRU) に保存された画像を配信する route。

セキュリティ:
- ID は `secrets.token_urlsafe(16)` で推測不可
- 認証なし (LINE platform からの取得を許可)
- TTL 経過 / 不在は 404
- 公開エンドポイントだが ID 知っているのは LINE 自身のみ → 実害なし
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Response, status
from services.image_store import get_image_store

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/line/image/{image_id}.png")
async def get_image(image_id: str) -> Response:
    """ImageStore から PNG を取り出し、Cache-Control 付きで返す。"""
    store = get_image_store()
    item = store.get(image_id)
    if item is None:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    data, content_type = item
    return Response(
        content=data,
        media_type=content_type,
        headers={
            # LINE のフェッチ後に再アクセスは少ないため短め
            "Cache-Control": "private, max-age=300",
        },
    )
