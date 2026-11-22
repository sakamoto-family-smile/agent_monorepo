"""ハンドラが共通で使うもの: 処理中のイベントの文脈・返事の末尾の状態表示・Quick Reply。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from app.deps import Deps
from app.line.api import postback_item
from app.line.events import LineEvent
from app.storage.modes import Mode
from app.storage.sessions import SessionRef

Messages = list[dict[str, Any]]

ANGLES = {"dtl": "後方", "face_on": "正面"}
# Quick Reply は 13 個まで。12 本 + 指定なし
CLUBS = ("1W", "3W", "5W", "UT", "5I", "6I", "7I", "8I", "9I", "PW", "AW", "SW")
NO_CLUB = "none"


@dataclass(frozen=True)
class Context:
    deps: Deps
    conn: AsyncConnection
    ev: LineEvent
    raw_event_id: int
    now: datetime

    @property
    def user_id(self) -> str:
        assert self.ev.user_id is not None
        return self.ev.user_id


def status(mode: Mode | None, session: SessionRef | None) -> str:
    parts = [p for p in ((mode.label if mode else None), (session.label if session else None)) if p]
    return "・".join(parts)


def with_status(body: str, session: SessionRef | None, mode: Mode | None = None) -> str:
    line = status(mode, session)
    return f"{body} ｜ {line}" if line else body


def video_label(params: dict[str, Any]) -> str:
    angle = ANGLES.get(params.get("angle") or "", "")
    club = params.get("club") or ""
    return "・".join(p for p in (angle, club) if p)


def angle_items(prefix: str) -> list[dict[str, Any]]:
    return [postback_item(label, f"{prefix}&angle={key}", label) for key, label in ANGLES.items()]


def club_items(prefix: str) -> list[dict[str, Any]]:
    items = [postback_item(club, f"{prefix}&club={club}", club) for club in CLUBS]
    return [*items, postback_item("指定なし", f"{prefix}&club={NO_CLUB}", "クラブ指定なし")]
