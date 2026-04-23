"""ingredient_resolver の正規化・曖昧マッチ・フォールバック挙動。"""

from __future__ import annotations

import pytest

from agents.ingredient_resolver import (
    INGREDIENT_ALIASES,
    ResolveResult,
    resolve,
    resolve_many,
)


class TestExactMatch:
    @pytest.mark.parametrize(
        "raw,expected_tag",
        [
            ("じゃがいも", "jagaimo"),
            ("ジャガイモ", "jagaimo"),
            ("じゃが芋", "jagaimo"),
            ("玉ねぎ", "tamanegi"),
            ("玉葱", "tamanegi"),
            ("にんじん", "ninjin"),
            ("人参", "ninjin"),
            ("鶏もも", "toriniku"),
            ("豚バラ", "butaniku"),
            ("豆腐", "tofu"),
            ("味噌", "miso"),
        ],
    )
    def test_known_aliases(self, raw, expected_tag):
        r = resolve(raw)
        assert r.tag == expected_tag
        assert r.method == "exact"
        assert r.confidence == 1.0


class TestNormalization:
    def test_full_width_alphanumeric_handled(self):
        # ＡＡＡ等の全角英字は NFKC で半角化される
        r = resolve("ＰＯＴＡＴＯ")
        assert r.tag == "jagaimo"

    def test_parenthesized_suffix_stripped(self):
        r = resolve("じゃがいも(冷蔵)")
        assert r.tag == "jagaimo"

    def test_decoration_marks_stripped(self):
        r = resolve("★じゃがいも★")
        assert r.tag == "jagaimo"

    def test_whitespace_stripped(self):
        r = resolve("  じゃがいも ")
        assert r.tag == "jagaimo"


class TestFuzzyMatch:
    def test_typo_matches_close_alias(self):
        # "じゃがいもs" のような小さなタイポはマッチして欲しい
        r = resolve("じゃがいもs")
        assert r.tag == "jagaimo"
        assert r.method in ("fuzzy", "exact")

    def test_unrelated_word_falls_back(self):
        r = resolve("これは絶対に食材ではない非常に長い文字列")
        assert r.tag is None
        assert r.method == "fallback"


class TestEdgeCases:
    def test_empty_string_returns_none_tag(self):
        r = resolve("")
        assert r.tag is None
        assert r.method == "fallback"

    def test_only_decoration_returns_none_tag(self):
        r = resolve("★★★")
        assert r.tag is None

    def test_resolve_many_preserves_order(self):
        results = resolve_many(["じゃがいも", "玉ねぎ", "にんじん"])
        assert [r.tag for r in results] == ["jagaimo", "tamanegi", "ninjin"]

    def test_resolve_many_with_unknown_keeps_raw(self):
        results = resolve_many(["じゃがいも", "謎の食材"])
        assert results[0].tag == "jagaimo"
        assert results[1].tag is None
        assert results[1].raw == "謎の食材"


class TestAliasDictIntegrity:
    def test_no_duplicate_alias_across_tags(self):
        seen: dict[str, str] = {}
        for tag, aliases in INGREDIENT_ALIASES.items():
            for alias in aliases:
                key = alias.lower()
                if key in seen and seen[key] != tag:
                    pytest.fail(f"alias '{alias}' assigned to both {seen[key]} and {tag}")
                seen[key] = tag

    def test_negi_and_tamanegi_are_different(self):
        """ねぎと玉ねぎは別物 (味噌汁の代用にならない)。"""
        assert resolve("ねぎ").tag == "negi"
        assert resolve("玉ねぎ").tag == "tamanegi"


class TestResolveResultDataclass:
    def test_is_immutable(self):
        r = resolve("じゃがいも")
        with pytest.raises(Exception):
            r.tag = "tamanegi"  # frozen dataclass

    def test_has_expected_fields(self):
        r = resolve("じゃがいも")
        assert isinstance(r, ResolveResult)
        assert hasattr(r, "raw")
        assert hasattr(r, "tag")
        assert hasattr(r, "confidence")
        assert hasattr(r, "method")
