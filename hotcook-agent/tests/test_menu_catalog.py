"""menu-catalog.json と services.menu_catalog のテスト。"""

from __future__ import annotations

import json
import os

import pytest

from models.menu import HotcookMenu, MenuCatalog
from services import menu_catalog


# ---------------------------------------------------------------------------
# 実 JSON ファイルの整合性 (Phase 1 シード 30 件)
# ---------------------------------------------------------------------------


class TestRealCatalogIntegrity:
    def test_catalog_has_at_least_30_menus(self):
        menu_catalog.reset_for_tests()
        catalog = menu_catalog.load_catalog()
        assert len(catalog.menus) >= 30

    def test_catalog_loads_via_pydantic(self):
        menu_catalog.reset_for_tests()
        catalog = menu_catalog.load_catalog()
        assert catalog.appliance == "KN-HW24H"
        assert catalog.version

    def test_no_duplicate_menu_no(self):
        menu_catalog.reset_for_tests()
        catalog = menu_catalog.load_catalog()
        nos = [m.menu_no for m in catalog.menus]
        assert len(nos) == len(set(nos))

    def test_categories_are_diverse(self):
        """30 件は最低でも 5 カテゴリにまたがるよう散らす設計。"""
        menu_catalog.reset_for_tests()
        catalog = menu_catalog.load_catalog()
        cats = {m.category for m in catalog.menus}
        assert len(cats) >= 5

    def test_every_menu_has_official_source(self):
        menu_catalog.reset_for_tests()
        catalog = menu_catalog.load_catalog()
        for m in catalog.menus:
            assert m.official_source, f"{m.menu_no} missing official_source"

    def test_every_menu_has_at_least_one_ingredient_tag(self):
        menu_catalog.reset_for_tests()
        catalog = menu_catalog.load_catalog()
        # ナムル等は tag が空でも OK にしているが、カバレッジ的に大半は埋める想定
        non_empty = sum(1 for m in catalog.menus if m.ingredient_tags)
        assert non_empty >= len(catalog.menus) - 2


# ---------------------------------------------------------------------------
# Pydantic スキーマ単体
# ---------------------------------------------------------------------------


class TestHotcookMenuSchema:
    def _valid(self, **overrides) -> dict:
        base = dict(
            menu_no="999", name="テスト料理", category="other",
            cook_minutes=30, reservation_ok=True, mixer_required=False,
            main_ingredients=["豚肉"], ingredient_tags=["butaniku"],
            official_source="test",
        )
        base.update(overrides)
        return base

    def test_valid_minimal(self):
        m = HotcookMenu.model_validate(self._valid())
        assert m.menu_no == "999"

    def test_cook_minutes_lower_bound(self):
        with pytest.raises(Exception):
            HotcookMenu.model_validate(self._valid(cook_minutes=2))

    def test_cook_minutes_upper_bound(self):
        with pytest.raises(Exception):
            HotcookMenu.model_validate(self._valid(cook_minutes=999))

    def test_ingredient_tags_lowercased(self):
        m = HotcookMenu.model_validate(self._valid(ingredient_tags=["BUTANIKU", " ToFu "]))
        assert m.ingredient_tags == ["butaniku", "tofu"]

    def test_invalid_category_rejected(self):
        with pytest.raises(Exception):
            HotcookMenu.model_validate(self._valid(category="not_a_category"))


class TestMenuCatalogSchema:
    def test_duplicate_menu_no_rejected(self):
        m1 = HotcookMenu.model_validate(dict(
            menu_no="001", name="A", category="other",
            cook_minutes=10, reservation_ok=True, mixer_required=False,
            official_source="x",
        ))
        m2 = HotcookMenu.model_validate(dict(
            menu_no="001", name="B", category="other",
            cook_minutes=10, reservation_ok=True, mixer_required=False,
            official_source="x",
        ))
        with pytest.raises(Exception):
            MenuCatalog(version="0.0.1", menus=[m1, m2])


# ---------------------------------------------------------------------------
# Service 関数
# ---------------------------------------------------------------------------


class TestServiceFunctions:
    def setup_method(self) -> None:
        menu_catalog.reset_for_tests()

    def test_find_menus_by_ingredient_tag_jagaimo_returns_nikujaga(self):
        menus = menu_catalog.find_menus_by_ingredient_tags(["jagaimo"])
        names = [m.name for m in menus]
        assert "肉じゃが" in names

    def test_find_menus_by_unknown_tag_returns_empty(self):
        menus = menu_catalog.find_menus_by_ingredient_tags(["unknown_tag_xyz"])
        assert menus == []

    def test_find_menu_by_no_returns_correct(self):
        m = menu_catalog.find_menu_by_no("001")
        assert m is not None
        assert m.name == "肉じゃが"

    def test_find_menu_by_no_returns_none_for_missing(self):
        assert menu_catalog.find_menu_by_no("xxx_not_exist") is None

    def test_get_all_menus_returns_list(self):
        menus = menu_catalog.get_all_menus()
        assert len(menus) >= 30


# ---------------------------------------------------------------------------
# ファイル不在時の挙動
# ---------------------------------------------------------------------------


@pytest.fixture
def restore_config_after():
    """テスト後に config / menu_catalog をデフォルト状態へ戻す。

    monkeypatch の teardown より先に env を消してから reload する必要があるため、
    monkeypatch に頼らず直接 os.environ を操作する。
    """
    yield
    os.environ.pop("MENU_CATALOG_PATH", None)
    import importlib
    import config
    importlib.reload(config)
    importlib.reload(menu_catalog)
    menu_catalog.reset_for_tests()


class TestCatalogLoadingErrors:
    def test_missing_file_raises_file_not_found(
        self, tmp_path, monkeypatch, restore_config_after
    ):
        menu_catalog.reset_for_tests()
        monkeypatch.setenv("MENU_CATALOG_PATH", str(tmp_path / "no_such.json"))
        import importlib
        import config
        importlib.reload(config)
        importlib.reload(menu_catalog)

        with pytest.raises(FileNotFoundError):
            menu_catalog.load_catalog()

    def test_invalid_json_raises_value_error(
        self, tmp_path, monkeypatch, restore_config_after
    ):
        menu_catalog.reset_for_tests()
        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        monkeypatch.setenv("MENU_CATALOG_PATH", str(bad))

        import importlib
        import config
        importlib.reload(config)
        importlib.reload(menu_catalog)

        with pytest.raises(json.JSONDecodeError):
            menu_catalog.load_catalog()
