"""共通 Skill loader のテスト。"""

from __future__ import annotations

import pytest

from fujisawa_platform.skills import KNOWN_SKILLS, get_skill


class TestGetSkill:
    @pytest.mark.parametrize("name", KNOWN_SKILLS)
    def test_loads_each_known_skill(self, name: str) -> None:
        """全 known skill が読み込めて、空文字でない。"""
        body = get_skill(name)
        assert isinstance(body, str)
        assert len(body) > 100

    @pytest.mark.parametrize("name", KNOWN_SKILLS)
    def test_each_skill_starts_with_skill_header(self, name: str) -> None:
        """各 SKILL.md は `# Skill:` ヘッダで始まる慣習。"""
        body = get_skill(name)
        first_line = body.splitlines()[0]
        assert first_line.startswith("# Skill:"), f"{name}: {first_line!r}"

    def test_unknown_skill_raises(self) -> None:
        """KNOWN_SKILLS にない名前は ValueError。"""
        with pytest.raises(ValueError, match="unknown skill"):
            get_skill("nonexistent")

    def test_known_skills_count(self) -> None:
        """proposal 0003 で約束した 5 つを確認。"""
        assert len(KNOWN_SKILLS) == 5
        assert set(KNOWN_SKILLS) == {
            "citation_format",
            "freshness_disclaimer",
            "yasashii_nihongo",
            "escalate_to_municipal",
            "line_output_format",
        }
