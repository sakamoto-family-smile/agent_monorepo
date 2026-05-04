"""Phase 3: Vertex Gemini に渡す tool 定義。

Gemini Function Declaration 仕様 (JSON Schema 風) で記述。

ツール一覧:
- query_events  : 期間 + 種別で集計値を取得 (count / sum_volume_ml / sum_sleep_minutes / raw)
- ask_clarification : ユーザに質問するための明示的なシグナル
                       (実 IO は無いが、LLM がこれを呼ぶことで「不足情報質問」を
                        capability_gap=asked_clarification として記録できる)
"""

from __future__ import annotations

from typing import Any

EVENT_TYPES = [
    "formula",
    "expressed_milk",
    "breast_milk",
    "sleep",
    "wake",
    "pee",
    "poo",
    "temperature",
    "weight",
    "height",
    "head_circumference",
    "bath",
    "medicine",
    "baby_food",
    "memo",
    "other",
]


QUERY_EVENTS_TOOL: dict[str, Any] = {
    "name": "query_events",
    "description": (
        "ぴよログの記録イベントを期間・種別で集計する。aggregation で出力形式を指定。"
        " - count : イベント件数 (指定 event_types の合計)"
        " - sum_volume_ml : ml の合計 (formula / expressed_milk / breast_milk のみ意味あり)"
        " - sum_sleep_minutes : 睡眠分数の合計 (wake のみ)"
        " - raw : 各イベントの (timestamp, type, value) を最大 50 件まで返す"
        " group_by を指定すると day / week / month 単位の小計を返す。"
        " 比較したい場合は 2 回呼び出して別々の期間の結果を取得すること。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "date_from": {
                "type": "string",
                "description": "YYYY-MM-DD 形式の開始日 (JST 含む)",
            },
            "date_to": {
                "type": "string",
                "description": "YYYY-MM-DD 形式の終了日 (inclusive、JST)",
            },
            "event_types": {
                "type": "array",
                "items": {"type": "string", "enum": EVENT_TYPES},
                "description": (
                    "対象 event_type のリスト。空の場合は全種類。"
                    "「ミルク」と言われたら通常 formula のみ、もし母乳含むなら "
                    "[formula, expressed_milk, breast_milk] を指定。"
                ),
            },
            "aggregation": {
                "type": "string",
                "enum": ["count", "sum_volume_ml", "sum_sleep_minutes", "raw"],
                "description": "集計方法",
            },
            "group_by": {
                "type": "string",
                "enum": ["none", "day", "week", "month"],
                "description": "集計の粒度。none なら期間全体で 1 値、day なら日次の dict、month なら月次の dict",
            },
        },
        "required": ["date_from", "date_to", "aggregation"],
    },
}


ASK_CLARIFICATION_TOOL: dict[str, Any] = {
    "name": "ask_clarification",
    "description": (
        "ユーザの質問が曖昧でデータ取得方針が定まらないとき、ユーザに具体的な質問を返すツール。"
        "例: 「ミルク」が回数 (count) なのか量 (sum_volume_ml) なのか不明な場合、"
        "このツールを呼んでから、question パラメータの内容をそのままユーザに返すこと。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "ユーザに返す質問文 (日本語、自然な口調で)",
            },
        },
        "required": ["question"],
    },
}


# Gemini が受け取る tool 定義リスト
TOOLS = [QUERY_EVENTS_TOOL, ASK_CLARIFICATION_TOOL]


__all__ = [
    "ASK_CLARIFICATION_TOOL",
    "EVENT_TYPES",
    "QUERY_EVENTS_TOOL",
    "TOOLS",
]
