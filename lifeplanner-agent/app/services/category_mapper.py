"""MF 大項目 → canonical カテゴリ変換。

- data/category_mappings/mf_to_canonical.yaml をロード
- 未知の大項目は ("other", "variable") にフォールバック
- 結果は Immutable な CanonicalCategory DC
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

_DEFAULT_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "category_mappings" / "mf_to_canonical.yaml"
)

ExpenseType = Literal["fixed", "variable", "income"]
_FALLBACK_KEY = "other"


@dataclass(frozen=True)
class CanonicalCategory:
    canonical: str
    expense_type: ExpenseType
    description: str = ""


@dataclass(frozen=True)
class CategoryMapper:
    mapping: dict[str, CanonicalCategory]
    fallback: CanonicalCategory

    def resolve(self, mf_category: str | None) -> CanonicalCategory:
        if not mf_category:
            return self.fallback
        return self.mapping.get(mf_category.strip(), self.fallback)


@lru_cache(maxsize=4)
def load_category_mapper(path: Path | None = None) -> CategoryMapper:
    src = path or _DEFAULT_PATH
    with src.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    mapping: dict[str, CanonicalCategory] = {}
    for mf_key, row in data.items():
        if not isinstance(row, dict):
            continue
        canonical = str(row.get("canonical", _FALLBACK_KEY))
        expense_type = str(row.get("expense_type", "variable"))
        if expense_type not in ("fixed", "variable", "income"):
            expense_type = "variable"
        mapping[mf_key] = CanonicalCategory(
            canonical=canonical,
            expense_type=expense_type,  # type: ignore[arg-type]
            description=str(row.get("description", "")),
        )

    fallback = mapping.get(
        "未分類",
        CanonicalCategory(canonical=_FALLBACK_KEY, expense_type="variable", description="分類不能"),
    )
    # fallback 自体も canonical="other" でなければ安全側に寄せる
    if fallback.canonical != _FALLBACK_KEY:
        fallback = CanonicalCategory(canonical=_FALLBACK_KEY, expense_type="variable", description="")

    return CategoryMapper(mapping=mapping, fallback=fallback)
