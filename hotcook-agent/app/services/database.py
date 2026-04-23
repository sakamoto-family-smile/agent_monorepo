"""SQLite 永続化レイヤ。

Phase 1 では最小限:
  - `inventory` テーブル: Phase 2 で本格的な冷蔵庫在庫管理をするが Phase 1 から基本 CRUD は用意
  - `suggestion_history` テーブル: 提案履歴 (誰に何を提案したか) — Phase 3 の学習基礎
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

import config

logger = logging.getLogger(__name__)


def _db_path() -> str:
    """settings.db_path を毎回 lookup (テストで importlib.reload(config) しても追従)。"""
    return config.settings.db_path


_SCHEMA = """
CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    quantity REAL NOT NULL DEFAULT 1,
    unit TEXT NOT NULL DEFAULT '個',
    location TEXT NOT NULL DEFAULT 'fridge',  -- fridge / freezer / pantry
    expires_on TEXT,                          -- ISO YYYY-MM-DD
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_inventory_name ON inventory(name);
CREATE INDEX IF NOT EXISTS idx_inventory_expires_on ON inventory(expires_on);

CREATE TABLE IF NOT EXISTS suggestion_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requested_ingredients TEXT NOT NULL,  -- JSON
    suggested_menu_nos TEXT NOT NULL,     -- JSON list
    mode TEXT NOT NULL,                    -- fast / agent
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_suggestion_history_created_at ON suggestion_history(created_at);
"""


async def init_db() -> None:
    """起動時 1 度だけ実行。テーブルが無ければ作成する。"""
    async with aiosqlite.connect(_db_path()) as db:
        await db.executescript(_SCHEMA)
        await db.commit()
    logger.info("sqlite initialized: %s", _db_path())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# inventory CRUD
# ---------------------------------------------------------------------------


async def create_inventory_item(item: dict[str, Any]) -> int:
    now = _now_iso()
    async with aiosqlite.connect(_db_path()) as db:
        cursor = await db.execute(
            """
            INSERT INTO inventory
              (name, quantity, unit, location, expires_on, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["name"],
                item.get("quantity", 1),
                item.get("unit", "個"),
                item.get("location", "fridge"),
                item.get("expires_on"),
                item.get("note"),
                now,
                now,
            ),
        )
        await db.commit()
        return cursor.lastrowid or 0


async def list_inventory_items(limit: int = 100) -> list[dict[str, Any]]:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, name, quantity, unit, location, expires_on, note, updated_at
            FROM inventory
            ORDER BY
              CASE WHEN expires_on IS NULL THEN 1 ELSE 0 END,
              expires_on ASC,
              updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def delete_inventory_item(item_id: int) -> bool:
    async with aiosqlite.connect(_db_path()) as db:
        cursor = await db.execute("DELETE FROM inventory WHERE id = ?", (item_id,))
        await db.commit()
        return (cursor.rowcount or 0) > 0


async def update_inventory_item(item_id: int, patch: dict[str, Any]) -> bool:
    fields: list[str] = []
    params: list[Any] = []
    for key in ("name", "quantity", "unit", "location", "expires_on", "note"):
        if key in patch:
            fields.append(f"{key} = ?")
            params.append(patch[key])
    if not fields:
        return False
    fields.append("updated_at = ?")
    params.append(_now_iso())
    params.append(item_id)

    sql = f"UPDATE inventory SET {', '.join(fields)} WHERE id = ?"
    async with aiosqlite.connect(_db_path()) as db:
        cursor = await db.execute(sql, params)
        await db.commit()
        return (cursor.rowcount or 0) > 0


# ---------------------------------------------------------------------------
# suggestion_history
# ---------------------------------------------------------------------------


async def save_suggestion_history(
    *,
    requested_ingredients: str,
    suggested_menu_nos: str,
    mode: str,
) -> int:
    async with aiosqlite.connect(_db_path()) as db:
        cursor = await db.execute(
            """
            INSERT INTO suggestion_history
              (requested_ingredients, suggested_menu_nos, mode, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (requested_ingredients, suggested_menu_nos, mode, _now_iso()),
        )
        await db.commit()
        return cursor.lastrowid or 0
