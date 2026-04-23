"""menu-catalog.json のロードとインデックス構築。

設計:
  - JSON は起動時に 1 度だけ読み、インメモリで保持する (145 件程度なので軽量)
  - ingredient_tag → MenuList の逆引きインデックスを構築して食材検索を O(1) 近似に
  - キャッシュは process-local。再ロードは `reload_catalog()` で明示
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import config
from models.menu import HotcookMenu, MenuCatalog

logger = logging.getLogger(__name__)


_catalog: MenuCatalog | None = None
_ingredient_index: dict[str, list[HotcookMenu]] | None = None


def _resolve_path() -> Path:
    """settings.menu_catalog_path を毎回 lookup (テストで importlib.reload(config) しても追従)。"""
    return Path(config.settings.menu_catalog_path)


def load_catalog(*, force: bool = False) -> MenuCatalog:
    """menu-catalog.json をロード (キャッシュあり)。

    Raises:
      FileNotFoundError: ファイル不在
      ValueError: JSON / Pydantic バリデーションエラー
    """
    global _catalog, _ingredient_index
    if _catalog is not None and not force:
        return _catalog

    path = _resolve_path()
    if not path.exists():
        raise FileNotFoundError(f"menu-catalog not found: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    catalog = MenuCatalog.model_validate(raw)

    # 逆引きインデックス構築
    idx: dict[str, list[HotcookMenu]] = defaultdict(list)
    for m in catalog.menus:
        for tag in m.ingredient_tags:
            idx[tag].append(m)

    _catalog = catalog
    _ingredient_index = dict(idx)
    logger.info(
        "menu catalog loaded: menus=%d, unique_ingredients=%d, path=%s",
        len(catalog.menus), len(idx), path,
    )
    return catalog


def reload_catalog() -> MenuCatalog:
    """テストやホットリロード用に強制再ロード。"""
    return load_catalog(force=True)


def get_all_menus() -> list[HotcookMenu]:
    return list(load_catalog().menus)


def find_menus_by_ingredient_tags(tags: Iterable[str]) -> list[HotcookMenu]:
    """指定タグのいずれかに該当するメニューをユニークで返す (順序保持)。"""
    load_catalog()
    assert _ingredient_index is not None
    seen: set[str] = set()
    result: list[HotcookMenu] = []
    for tag in tags:
        for m in _ingredient_index.get(tag.lower(), []):
            if m.menu_no not in seen:
                seen.add(m.menu_no)
                result.append(m)
    return result


def find_menu_by_no(menu_no: str) -> HotcookMenu | None:
    for m in load_catalog().menus:
        if m.menu_no == menu_no:
            return m
    return None


def reset_for_tests() -> None:
    """テスト用: キャッシュ初期化。"""
    global _catalog, _ingredient_index
    _catalog = None
    _ingredient_index = None
