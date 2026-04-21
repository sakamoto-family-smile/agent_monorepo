"""Flex Message JSON の生成。

SDK 依存のない純関数で Flex JSON (dict) を返す:
  - `narrative_bubble`: /summarize / /compare の返信で使う見出し + 本文バブル
  - `scenarios_carousel`: /scenarios の返信で使うシナリオ一覧カルーセル

LINE の上限:
  - carousel は最大 12 bubble (ただし実用上 10 以下が安全)
  - 1 text component は 2000 文字まで
  - alt_text は 400 文字まで
"""

from __future__ import annotations

_HEADER_COLOR = "#1E40AF"
_SUBTLE_COLOR = "#6B7280"

_MAX_NARRATIVE_CHARS = 1800
_MAX_DESC_CHARS = 200


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def narrative_bubble(*, title: str, body_text: str) -> dict:
    """見出し + 本文の 1 bubble。"""
    return {
        "type": "bubble",
        "size": "giga",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": _HEADER_COLOR,
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "text",
                    "text": _truncate(title, 60),
                    "color": "#FFFFFF",
                    "weight": "bold",
                    "size": "md",
                    "wrap": True,
                }
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": _truncate(body_text, _MAX_NARRATIVE_CHARS),
                    "wrap": True,
                    "size": "sm",
                }
            ],
        },
    }


def _scenario_bubble(*, scenario_id: int, name: str, description: str | None) -> dict:
    contents: list[dict] = [
        {"type": "text", "text": f"#{scenario_id}", "color": _SUBTLE_COLOR, "size": "xs"},
        {
            "type": "text",
            "text": _truncate(name, 60),
            "weight": "bold",
            "size": "md",
            "wrap": True,
        },
    ]
    if description:
        contents.append(
            {
                "type": "text",
                "text": _truncate(description, _MAX_DESC_CHARS),
                "wrap": True,
                "color": "#444444",
                "size": "xs",
            }
        )
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": contents,
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "color": _HEADER_COLOR,
                    "action": {
                        "type": "message",
                        "label": "要約",
                        "text": f"/summarize {scenario_id}",
                    },
                }
            ],
        },
    }


def scenarios_carousel(scenarios: list[tuple[int, str, str | None]]) -> dict:
    """scenarios: `(id, name, description)` のリスト。

    10 件までを 1 carousel に詰める。超過分は呼び出し側で切り落とすこと。
    """
    limited = scenarios[:10]
    return {
        "type": "carousel",
        "contents": [
            _scenario_bubble(scenario_id=s[0], name=s[1], description=s[2])
            for s in limited
        ],
    }
