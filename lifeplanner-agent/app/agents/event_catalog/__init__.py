"""ライフイベントカタログ。

各イベントは (パラメータ, 時期) → 年次キャッシュフロー差分 (CashFlowDelta list)
に変換する純粋関数として実装する。

Phase 2 スコープ:
  - E01: 出産・育児 (出産費用・育休給付・児童手当・保育料・教育費)
"""

from __future__ import annotations

from agents.event_catalog.birth import BirthEventParams, expand_birth_event
from agents.event_catalog.types import CashFlowDelta, EventCategory

__all__ = [
    "BirthEventParams",
    "CashFlowDelta",
    "EventCategory",
    "expand_birth_event",
]
