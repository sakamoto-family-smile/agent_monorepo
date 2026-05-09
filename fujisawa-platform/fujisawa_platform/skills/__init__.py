"""共通 Skill File 群。

consumer agent (info-bot / 保活) は LLM プロンプトに動的注入してエージェントの
振る舞いを制御する。Markdown ファイルとしてパッケージに同梱し、`get_skill()` で
読み出す。
"""

from __future__ import annotations

from importlib.resources import files

_PACKAGE = "fujisawa_platform.skills"

KNOWN_SKILLS = (
    "citation_format",
    "freshness_disclaimer",
    "yasashii_nihongo",
    "escalate_to_municipal",
    "line_output_format",
)


def get_skill(name: str) -> str:
    """Skill File を文字列として返す。

    Args:
        name: KNOWN_SKILLS のいずれか。

    Returns:
        Markdown のテキスト。

    Raises:
        ValueError: 未知の skill 名。
        FileNotFoundError: 同名 .md ファイルが存在しない場合。
    """
    if name not in KNOWN_SKILLS:
        raise ValueError(f"unknown skill: {name!r} (known: {KNOWN_SKILLS})")
    resource = files(_PACKAGE).joinpath(f"{name}.md")
    return resource.read_text(encoding="utf-8")


__all__ = ["KNOWN_SKILLS", "get_skill"]
