"""scripts/seed_menu_catalog.py が menu-catalog.json を正しく生成できることを保証する。

- リテラル定義 (SEED_MENUS) が Pydantic スキーマを満たす
- カテゴリ分布が散っている (5 カテゴリ以上)
- ファイル出力 (--write) が実 catalog を上書き可能
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _import_seed_module():
    spec = importlib.util.spec_from_file_location(
        "seed_menu_catalog",
        REPO_ROOT / "scripts" / "seed_menu_catalog.py",
    )
    assert spec and spec.loader
    sys.path.insert(0, str(REPO_ROOT / "app"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSeedScript:
    def test_seed_has_at_least_30_entries(self):
        mod = _import_seed_module()
        assert len(mod.SEED_MENUS) >= 30

    def test_build_catalog_validates(self):
        mod = _import_seed_module()
        catalog = mod.build_catalog()
        assert catalog.appliance == "KN-HW24H"
        assert len(catalog.menus) == len(mod.SEED_MENUS)

    def test_catalog_has_at_least_5_categories(self):
        mod = _import_seed_module()
        catalog = mod.build_catalog()
        assert len({m.category for m in catalog.menus}) >= 5

    def test_no_duplicate_menu_no_in_seed(self):
        mod = _import_seed_module()
        nos = [m["menu_no"] for m in mod.SEED_MENUS]
        assert len(nos) == len(set(nos))

    def test_main_writes_valid_json(self, tmp_path, monkeypatch):
        mod = _import_seed_module()
        target = tmp_path / "out.json"
        monkeypatch.setattr(mod, "OUTPUT_PATH", target)
        rc = mod.main()
        assert rc == 0
        assert target.exists()
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["appliance"] == "KN-HW24H"
        assert len(data["menus"]) >= 30

    @pytest.mark.parametrize("required_field", ["menu_no", "name", "category", "cook_minutes"])
    def test_every_seed_entry_has_required_field(self, required_field):
        mod = _import_seed_module()
        for entry in mod.SEED_MENUS:
            assert required_field in entry, f"{entry.get('menu_no')} missing {required_field}"
