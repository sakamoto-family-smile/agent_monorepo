"""GET/POST/PUT/DELETE /api/inventory — 冷蔵庫在庫の基本 CRUD。

Phase 1 では基礎テーブルのみ。Phase 2 で消費期限ベースの優先提案や写真→在庫追加に発展する。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from models.recipe import InventoryItem, InventoryListResponse
from services.database import (
    create_inventory_item,
    delete_inventory_item,
    list_inventory_items,
    update_inventory_item,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/inventory", response_model=InventoryListResponse)
async def list_inventory(limit: int = 100) -> InventoryListResponse:
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit must be 1..500")
    rows = await list_inventory_items(limit=limit)
    items = [InventoryItem.model_validate(r) for r in rows]
    return InventoryListResponse(items=items, total=len(items))


@router.post("/inventory", response_model=InventoryItem, status_code=201)
async def create_inventory(item: InventoryItem) -> InventoryItem:
    new_id = await create_inventory_item(item.model_dump(exclude={"id", "updated_at"}))
    rows = await list_inventory_items(limit=500)
    for r in rows:
        if r["id"] == new_id:
            return InventoryItem.model_validate(r)
    raise HTTPException(status_code=500, detail="created item not found after insert")


@router.put("/inventory/{item_id}", response_model=InventoryItem)
async def update_inventory(item_id: int, patch: InventoryItem) -> InventoryItem:
    payload = patch.model_dump(exclude={"id", "updated_at"}, exclude_none=True)
    if not payload:
        raise HTTPException(status_code=422, detail="empty patch")
    updated = await update_inventory_item(item_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail=f"item {item_id} not found")
    rows = await list_inventory_items(limit=500)
    for r in rows:
        if r["id"] == item_id:
            return InventoryItem.model_validate(r)
    raise HTTPException(status_code=500, detail="updated item not found after update")


@router.delete("/inventory/{item_id}")
async def delete_inventory(item_id: int) -> dict:
    deleted = await delete_inventory_item(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"item {item_id} not found")
    return {"deleted": item_id}
