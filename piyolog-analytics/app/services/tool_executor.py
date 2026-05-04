"""Phase 3: tool 名 + 引数 → 実 DB クエリの振り分け。

`consultation.py` から `execute_tool(name, args, repo, family_id)` で呼ばれる。
戻り値は LLM に渡す JSON 文字列 (Gemini の tool_response)。

設計判断:
- repo.fetch_events_in_range の結果 (タプル列) を受け取り集計
- 出力は LLM が parse しやすい dict / list 構造を JSON シリアライズ
- 例外時は capability_gap="tool_error" マーカーになるよう、上位で捕まえる
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9), "Asia/Tokyo")

# event_repo の戻り値 index
_TS = 0
_DATE = 1
_TYPE = 2
_VOLUME_ML = 3
_LEFT_MIN = 4
_RIGHT_MIN = 5
_SLEEP_MIN = 6


async def execute_tool(
    *,
    name: str,
    args: dict[str, Any],
    repo,
    family_id: str,
) -> str:
    """tool 名と引数を受け取り、LLM に返す JSON 文字列を返す。

    対応 tool: query_events / ask_clarification
    未知の tool は ValueError。
    """
    if name == "query_events":
        return await _execute_query_events(args, repo=repo, family_id=family_id)
    if name == "ask_clarification":
        # 実 IO 無し: question 自体を結果として返すが、消費側でユーザに reply する
        question = args.get("question", "")
        return json.dumps({"question": question}, ensure_ascii=False)
    raise ValueError(f"unknown tool: {name}")


async def _execute_query_events(args: dict[str, Any], *, repo, family_id: str) -> str:
    date_from = args.get("date_from", "")
    date_to = args.get("date_to", "")
    event_types: list[str] = args.get("event_types") or []
    aggregation = args.get("aggregation", "count")
    group_by = args.get("group_by", "none")

    events = await repo.fetch_events_in_range(
        family_id=family_id, date_from=date_from, date_to=date_to
    )
    if event_types:
        target = set(event_types)
        events = [e for e in events if e[_TYPE] in target]

    if aggregation == "raw":
        # 最大 50 件まで安全に返す
        truncated = events[:50]
        rows = [
            {
                "timestamp": e[_TS],
                "date": e[_DATE],
                "type": e[_TYPE],
                "volume_ml": e[_VOLUME_ML],
                "left_minutes": e[_LEFT_MIN],
                "right_minutes": e[_RIGHT_MIN],
                "sleep_minutes": e[_SLEEP_MIN],
            }
            for e in truncated
        ]
        return json.dumps(
            {
                "date_from": date_from,
                "date_to": date_to,
                "total_count": len(events),
                "returned_count": len(rows),
                "events": rows,
            },
            ensure_ascii=False,
        )

    # 集計関数を選択
    aggregator = _resolve_aggregator(aggregation)

    if group_by == "none":
        value = aggregator(events)
        result = {
            "date_from": date_from,
            "date_to": date_to,
            "event_types": event_types or "all",
            "aggregation": aggregation,
            "value": value,
            "n_events": len(events),
        }
        return json.dumps(result, ensure_ascii=False)

    # group_by day / week / month
    bucketed = _bucket_events(events, group_by=group_by)
    grouped = {bucket: aggregator(rows) for bucket, rows in bucketed.items()}
    result = {
        "date_from": date_from,
        "date_to": date_to,
        "event_types": event_types or "all",
        "aggregation": aggregation,
        "group_by": group_by,
        "groups": grouped,
        "n_events": len(events),
    }
    return json.dumps(result, ensure_ascii=False)


def _resolve_aggregator(name: str) -> Callable[[list[tuple]], float | int]:
    if name == "count":
        return lambda rows: len(rows)
    if name == "sum_volume_ml":
        return lambda rows: round(sum((r[_VOLUME_ML] or 0.0) for r in rows), 1)
    if name == "sum_sleep_minutes":
        return lambda rows: int(sum((r[_SLEEP_MIN] or 0) for r in rows))
    raise ValueError(f"unknown aggregation: {name}")


def _bucket_events(events: list[tuple], *, group_by: str) -> dict[str, list[tuple]]:
    """events を day / week / month 単位に分類 (キーは ISO 文字列)。"""
    buckets: dict[str, list[tuple]] = defaultdict(list)
    for e in events:
        ts = datetime.fromisoformat(e[_TS]).astimezone(JST)
        if group_by == "day":
            key = ts.date().isoformat()
        elif group_by == "week":
            # ISO week (YYYY-Www)
            iso = ts.isocalendar()
            key = f"{iso.year}-W{iso.week:02d}"
        elif group_by == "month":
            key = f"{ts.year:04d}-{ts.month:02d}"
        else:
            raise ValueError(f"unknown group_by: {group_by}")
        buckets[key].append(e)
    # 順序を保つため sorted dict として返す
    return dict(sorted(buckets.items()))


__all__ = ["execute_tool"]
