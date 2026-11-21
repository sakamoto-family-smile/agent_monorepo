"""LIFF フォームと、そのフォームが叩く JSON API。

- GET  /liff            : 入力フォーム（HTML）。LIFF ID を埋め込んで返す。
- GET  /api/relations   : 間柄の選択肢一覧
- GET  /api/entries     : 一覧 / 検索（?q=）
- POST /api/entries     : 1 件登録

レスポンスは `{success, data, error}` の共通エンベロープ。

認可について: 本番では LIFF の ID トークンを検証して本人確認するのが望ましい。
ここでは MVP として `created_by` を受け取り、検証フックのみ用意する（TODO）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from app.deps import AppDeps
from app.models import EntryDraft, EntryValidationError, Relation
from app.services.roster import DuplicateEntryError

router = APIRouter()

_FORM_PATH = Path(__file__).resolve().parent.parent / "ui" / "form.html"


def _envelope(
    *, data: Any = None, error: str | None = None, status_code: int = 200
) -> JSONResponse:
    return JSONResponse(
        {"success": error is None, "data": data, "error": error},
        status_code=status_code,
    )


@router.get("/liff", response_class=HTMLResponse)
async def liff_form(request: Request) -> HTMLResponse:
    """LIFF 入力フォームを返す。LIFF ID をテンプレートに差し込む。"""
    deps: AppDeps = request.app.state.deps
    html = _FORM_PATH.read_text(encoding="utf-8")
    html = html.replace("{{LIFF_ID}}", deps.settings.liff_id)
    return HTMLResponse(html)


@router.get("/api/relations")
async def list_relations() -> JSONResponse:
    """間柄の選択肢一覧（フォームのプルダウン用）。"""
    return _envelope(data=Relation.choices())


@router.get("/api/entries")
async def list_entries(request: Request, q: str = "") -> JSONResponse:
    """名簿の一覧 / 検索。"""
    deps: AppDeps = request.app.state.deps
    entries = deps.roster.search(q) if q else deps.roster.list_all()
    return _envelope(data=[e.model_dump() for e in entries])


class CreateEntryRequest(BaseModel):
    """LIFF フォームからの登録リクエスト。"""

    name: str = ""
    kana: str = ""
    zip: str = ""
    address: str = ""
    relation: str = ""
    note: str = ""
    created_by: str = ""


@router.post("/api/entries")
async def create_entry(request: Request, payload: CreateEntryRequest) -> JSONResponse:
    """1 件登録する。検証・重複エラーはユーザー向けメッセージで返す。"""
    deps: AppDeps = request.app.state.deps
    draft = EntryDraft(
        name=payload.name,
        kana=payload.kana,
        zip=payload.zip,
        address=payload.address,
        relation=payload.relation,
        note=payload.note,
    )
    try:
        entry = deps.roster.register(draft, created_by=payload.created_by)
    except EntryValidationError as exc:
        return _envelope(error=str(exc), status_code=422)
    except DuplicateEntryError as exc:
        return _envelope(error=str(exc), status_code=409)
    return _envelope(data=entry.model_dump(), status_code=201)


__all__ = ["router"]
