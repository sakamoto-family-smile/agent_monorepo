"""原本の保存。届いたイベントは JSON ファイル (data/raw/YYYY/MM/) と raw_events の両方に残す。

JSON ファイルは DB が壊れたときの最後の拠り所なので、DB より先に書く。
同じ webhookEventId (LINE の再送・ボタンの連打で届く同じイベント) は 2 回目以降を保存しない。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.config import Paths
from app.line.events import LineEvent
from app.storage.tables import raw_events
from app.timeutil import from_ms, iso


def raw_path(paths: Paths, ev: LineEvent, tz: ZoneInfo) -> Path:
    at = from_ms(ev.timestamp_ms).astimezone(tz)
    # webhookEventId は ULID (英数字) だが、念のためパスに使えない文字を落とす
    safe = "".join(c for c in ev.webhook_event_id if c.isalnum())
    return paths.raw / f"{at:%Y}" / f"{at:%m}" / f"{safe}.json"


def write_raw_file(paths: Paths, ev: LineEvent, tz: ZoneInfo) -> Path:
    path = raw_path(paths, ev, tz)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ev.raw, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


async def save_raw(
    conn: AsyncConnection, paths: Paths, ev: LineEvent, now: datetime, tz: ZoneInfo
) -> int | None:
    """新しいイベントなら raw_events.id を、保存済みなら None を返す。"""
    assert ev.user_id is not None
    write_raw_file(paths, ev, tz)
    stmt = (
        insert(raw_events)
        .values(
            webhook_event_id=ev.webhook_event_id,
            line_message_id=ev.message_id,
            user_id=ev.user_id,
            type=ev.type,
            message_type=ev.message_type,
            payload_json=json.dumps(ev.raw, ensure_ascii=False, sort_keys=True),
            is_redelivery=ev.is_redelivery,
            event_at=iso(from_ms(ev.timestamp_ms)),
            received_at=iso(now),
        )
        .on_conflict_do_nothing(index_elements=["webhook_event_id"])
    )
    res = await conn.execute(stmt)
    if res.rowcount == 0:
        return None
    return int(res.inserted_primary_key[0])
