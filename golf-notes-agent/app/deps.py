"""ハンドラ・ジョブが使う依存 (設定・DB・LINE API・時計) をまとめる。"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.line.api import LineApi
from app.timeutil import Clock


@dataclass(frozen=True)
class Deps:
    settings: Settings
    engine: AsyncEngine
    line: LineApi
    clock: Clock
