"""Anthropic API レスポンスから text を抽出する共通ヘルパ。"""

from __future__ import annotations

from typing import Any


def extract_text(resp: Any) -> str:
    """messages.create のレスポンスから TextBlock を結合して返す。"""
    parts: list[str] = []
    for block in resp.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "".join(parts).strip()
