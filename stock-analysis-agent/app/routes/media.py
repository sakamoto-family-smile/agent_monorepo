"""PROPOSAL-0011 P1: チャート画像 / 全文レポートの配信 route。

- `GET /api/line/image/{id}.png` — LINE ImageMessage 用の PNG 配信
- `GET /api/line/report/{id}.md` — Claude 生成の全文レポート (Markdown) を
  添付ファイルとして DL させる (Content-Disposition: attachment)

セキュリティ:
- ID は `secrets.token_urlsafe(16)` で推測不可
- 認証なし (LINE platform / 本人のブラウザからの取得を許可)
- TTL 経過 / 不在は 404
- 公開エンドポイントだが ID を知るのは分析を実行した本人と LINE のみ → 実害は小
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Response, status

from services.blob_store import get_image_store, get_report_store

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/line/image/{image_id}.png")
async def get_image(image_id: str) -> Response:
    """ImageStore から PNG を取り出し、Cache-Control 付きで返す。"""
    item = get_image_store().get(image_id)
    if item is None:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    data, content_type = item
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/line/report/{report_id}.md")
async def get_report(report_id: str) -> Response:
    """ReportStore から全文 Markdown を取り出し、添付ファイルとして返す。"""
    item = get_report_store().get(report_id)
    if item is None:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    data, content_type = item
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="report_{report_id}.md"',
            "Cache-Control": "private, max-age=300",
        },
    )


@router.get("/line/report/{report_id}.html")
async def get_report_html(report_id: str) -> Response:
    """ReportStore から HTML 版レポートを取り出し、インライン表示で返す。"""
    item = get_report_store().get(report_id)
    if item is None:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    data, content_type = item
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=300"},
    )
