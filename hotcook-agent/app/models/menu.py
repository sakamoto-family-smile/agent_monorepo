"""ホットクック内蔵メニューのスキーマ。

データソースはシャープ公式メニューサイト / 取扱説明書の **事実情報のみ**:
  - メニュー番号、名称、カテゴリ、調理時間、まぜ技ユニット要否、予約調理可否

詳細手順 / 分量 / レシピ写真は著作権配慮のため格納しない。応答時は
`official_source` (取扱説明書ページ等) を返してユーザーが原典に当たれるようにする。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


# 公式に存在するカテゴリの一部 (Phase 1 シードでカバーする範囲のみ)
MenuCategory = Literal[
    "nimono",        # 煮物
    "curry_stew",    # カレー・シチュー
    "soup",          # スープ
    "steam",         # 蒸し料理
    "pasta_rice",    # 麺・米
    "ferment_lowtemp",  # 発酵・低温調理
    "side_dish",     # 副菜
    "other",
]


class HotcookMenu(BaseModel):
    """KN-HW24H 内蔵メニューの 1 件。"""

    menu_no: str = Field(..., description="シャープ公式番号 (例: '001')")
    name: str = Field(..., description="メニュー名 (例: '肉じゃが')")
    name_kana: str | None = Field(None, description="カナ表記 (検索用)")
    category: MenuCategory
    cook_minutes: int = Field(..., ge=5, le=720, description="標準調理時間 (分)")
    reservation_ok: bool = Field(..., description="予約調理可否")
    mixer_required: bool = Field(..., description="まぜ技ユニットを使うか")
    serves: int = Field(default=4, ge=1, le=10, description="標準何人前か")

    # 食材 (主な材料 / 任意材料 / 正規化タグ)
    main_ingredients: list[str] = Field(
        default_factory=list, description="主材料 (人間可読、例: 'じゃがいも')"
    )
    optional_ingredients: list[str] = Field(default_factory=list)
    ingredient_tags: list[str] = Field(
        default_factory=list,
        description="正規化食材タグ (例: 'jagaimo')。ingredient_resolver の出力と突合する",
    )

    # 補助メタ
    season_tags: list[str] = Field(
        default_factory=lambda: ["all"],
        description="季節タグ (spring/summer/autumn/winter/all)",
    )
    skill_tags: list[str] = Field(
        default_factory=list, description="特徴タグ (例: '無水', '低温')"
    )

    # 出典 / 検証フラグ
    official_source: str = Field(..., description="取扱説明書ページ番号や公式URL")
    verified: bool = Field(
        default=False,
        description="True = 取扱説明書 / 公式サイトで人手検証済み。False = LLM 起草段階",
    )

    @field_validator("menu_no")
    @classmethod
    def _strip_menu_no(cls, v: str) -> str:
        return v.strip()

    @field_validator("ingredient_tags")
    @classmethod
    def _lowercase_tags(cls, v: list[str]) -> list[str]:
        return [t.strip().lower() for t in v if t and t.strip()]


class MenuCatalog(BaseModel):
    """menu-catalog.json のルート。"""

    version: str = Field(..., description="例: '0.1.0'")
    appliance: str = Field(default="KN-HW24H")
    source_note: str = Field(
        default="シャープ公式メニュー一覧 / KN-HW24H 取扱説明書 (事実情報のみ抽出)"
    )
    menus: list[HotcookMenu]

    @field_validator("menus")
    @classmethod
    def _no_duplicate_menu_no(cls, v: list[HotcookMenu]) -> list[HotcookMenu]:
        seen: set[str] = set()
        for m in v:
            if m.menu_no in seen:
                raise ValueError(f"duplicate menu_no: {m.menu_no}")
            seen.add(m.menu_no)
        return v
