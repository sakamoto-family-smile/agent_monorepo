"""system プロンプトのペイロード整形。"""

from __future__ import annotations

from typing import Any


def system_payload(system: str, *, cache: bool) -> str | list[dict[str, Any]]:
    """system 文字列を Anthropic API の system 引数形式に変換する。

    - cache=False → そのまま str を返す (既存動作)
    - cache=True  → [{"type":"text", "text":..., "cache_control":{"type":"ephemeral"}}]
    """
    if not cache:
        return system
    return [
        {
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }
    ]
