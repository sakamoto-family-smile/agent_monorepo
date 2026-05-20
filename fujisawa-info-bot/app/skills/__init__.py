"""Skill prompt 群 — markdown を読込んで LLM の system prompt に注入する。

各 markdown は人間にも読める形式で「やってほしいこと」を記述し、 本モジュールで
ファイル内容を文字列として返すヘルパを提供する。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_SKILLS_DIR = Path(__file__).parent


@lru_cache(maxsize=16)
def load_skill(name: str) -> str:
    """`<name>.md` の内容を文字列で返す (キャッシュ済)。

    Args:
        name: 拡張子無しの skill 名 (例: "category_routing")
    """
    path = _SKILLS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"skill not found: {path}")
    return path.read_text(encoding="utf-8")


__all__ = ["load_skill"]
