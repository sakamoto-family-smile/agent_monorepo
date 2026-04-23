"""recipe_suggester のスコアリングと挙動。"""

from __future__ import annotations

import pytest

from agents.recipe_suggester import suggest_recipes
from models.recipe import IngredientInput, SuggestRequest
from services import menu_catalog


@pytest.fixture(autouse=True)
def _reset_catalog():
    menu_catalog.reset_for_tests()


def _req(ingredients: list[str], **overrides) -> SuggestRequest:
    payload = dict(
        ingredients=[IngredientInput(name=n) for n in ingredients],
        top_n=5,
        mode="fast",
    )
    payload.update(overrides)
    return SuggestRequest(**payload)


class TestBasicSuggestion:
    def test_jagaimo_gyuniku_tamanegi_suggests_nikujaga(self):
        result = suggest_recipes(_req(["じゃがいも", "牛肉", "玉ねぎ"]))
        assert len(result.candidates) > 0
        names = [c.name for c in result.candidates]
        assert "肉じゃが" in names

    def test_top_candidate_for_curry_ingredients_is_curry_or_stew(self):
        result = suggest_recipes(_req(["鶏肉", "玉ねぎ", "トマト", "にんじん"]))
        # 無水カレーが上位に来てほしい
        top_names = [c.name for c in result.candidates[:3]]
        assert any("カレー" in n or "シチュー" in n for n in top_names)

    def test_butaniku_daikon_suggests_tonjiru_or_kakuni(self):
        result = suggest_recipes(_req(["豚肉", "大根"]))
        names = [c.name for c in result.candidates]
        # どちらか or 豚バラ大根のうま煮が含まれる
        assert any(n in names for n in ("豚汁", "豚の角煮", "豚バラ大根のうま煮"))


class TestRanking:
    def test_results_sorted_descending_by_score(self):
        result = suggest_recipes(_req(["豚肉", "大根", "にんじん", "ごぼう", "味噌"]))
        scores = [c.score for c in result.candidates]
        assert scores == sorted(scores, reverse=True)
        # rank は 1 始まりで連番
        for i, c in enumerate(result.candidates, start=1):
            assert c.rank == i

    def test_score_is_in_0_100_range(self):
        result = suggest_recipes(_req(["豚肉", "大根"]))
        for c in result.candidates:
            assert 0 < c.score <= 100


class TestFilters:
    def test_max_cook_minutes_filter_excludes_long_recipes(self):
        # ヨーグルト (420分) や角煮 (90分) は除外される
        result = suggest_recipes(_req(["豚肉", "大根"], max_cook_minutes=30))
        for c in result.candidates:
            assert c.cook_minutes <= 30

    def test_require_reservation_excludes_non_reservation(self):
        # 茶碗蒸し等は予約不可
        result = suggest_recipes(_req(["卵", "鶏肉"], require_reservation=True))
        for c in result.candidates:
            assert c.reservation_ok is True

    def test_require_no_mixer_excludes_mixer_required(self):
        result = suggest_recipes(_req(["鶏むね肉"], require_no_mixer=True))
        for c in result.candidates:
            assert c.mixer_required is False

    def test_exclude_menu_nos_filter_works(self):
        result = suggest_recipes(_req(["じゃがいも", "牛肉", "玉ねぎ"], exclude_menu_nos=["001"]))
        assert "001" not in [c.menu_no for c in result.candidates]


class TestEdgeCases:
    def test_empty_match_returns_fallback_hint(self):
        result = suggest_recipes(_req(["まったく未知の食材"]))
        assert result.candidates == []
        assert result.fallback_hint is not None

    def test_top_n_respected(self):
        result = suggest_recipes(_req(["豚肉", "大根", "にんじん", "ごぼう", "味噌"], top_n=2))
        assert len(result.candidates) <= 2

    def test_disclaimer_always_present(self):
        result = suggest_recipes(_req(["じゃがいも", "牛肉", "玉ねぎ"]))
        assert "実機" in result.disclaimer or "公式" in result.disclaimer

    def test_total_scanned_matches_catalog_size(self):
        result = suggest_recipes(_req(["じゃがいも"]))
        assert result.total_scanned >= 30


class TestRationaleAndIngredientMatch:
    def test_rationale_includes_matched_ingredients(self):
        result = suggest_recipes(_req(["じゃがいも", "牛肉", "玉ねぎ"]))
        nikujaga = next((c for c in result.candidates if c.name == "肉じゃが"), None)
        assert nikujaga is not None
        # rationale テキストに matched_main の食材名が含まれる
        joined = " / ".join(nikujaga.rationale)
        assert "じゃがいも" in joined or "牛肉" in joined or "玉ねぎ" in joined

    def test_ingredient_match_detail_populated(self):
        result = suggest_recipes(_req(["じゃがいも", "牛肉", "玉ねぎ"]))
        nikujaga = next((c for c in result.candidates if c.name == "肉じゃが"), None)
        assert nikujaga is not None
        assert nikujaga.ingredient_match.matched_main
        # 主材料 3 件すべて揃っているので missing_main は空
        assert nikujaga.ingredient_match.missing_main == []

    def test_partial_ingredients_show_missing(self):
        # 玉ねぎ無し
        result = suggest_recipes(_req(["じゃがいも", "牛肉"]))
        nikujaga = next((c for c in result.candidates if c.name == "肉じゃが"), None)
        if nikujaga is not None:
            assert "玉ねぎ" in nikujaga.ingredient_match.missing_main


class TestRequestValidation:
    def test_empty_ingredients_rejected(self):
        with pytest.raises(Exception):
            SuggestRequest(ingredients=[])

    def test_top_n_upper_bound(self):
        with pytest.raises(Exception):
            SuggestRequest(
                ingredients=[IngredientInput(name="a")], top_n=999
            )
