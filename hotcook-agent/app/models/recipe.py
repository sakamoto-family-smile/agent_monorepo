"""レシピ提案の Request / Response スキーマ。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class IngredientInput(BaseModel):
    """1 食材の入力。"""

    name: str = Field(..., min_length=1, description="食材名 (例: 'じゃがいも')")
    quantity: float | None = Field(default=None, ge=0, description="数量 (任意)")
    unit: str | None = Field(default=None, description="単位 (個 / g / 本 等)")


class SuggestRequest(BaseModel):
    """`POST /api/recipes/suggest` のリクエスト。"""

    ingredients: list[IngredientInput] = Field(
        ..., min_length=1, description="冷蔵庫にある食材リスト"
    )
    top_n: int = Field(default=5, ge=1, le=20)
    max_cook_minutes: int | None = Field(
        default=None, ge=5, le=720,
        description="この時間以内のメニューに絞る (None なら制限なし)",
    )
    require_reservation: bool = Field(
        default=False, description="予約調理可能なメニューに絞る"
    )
    require_no_mixer: bool = Field(
        default=False,
        description="True にするとまぜ技ユニット不要メニューのみ (出張中などで本体だけ稼働させたい場合)",
    )
    mode: Literal["fast", "agent"] = Field(
        default="fast",
        description=(
            "fast: ルールベースのスコアリングのみ (Claude を呼ばない)。"
            " agent: ルールベース結果を Claude に渡して根拠テキストを生成 (Phase 1 後半で実装)"
        ),
    )
    exclude_menu_nos: list[str] = Field(
        default_factory=list, description="直近作った等の理由で除外したいメニュー番号"
    )


class IngredientMatch(BaseModel):
    """提案候補の食材マッチ詳細。"""

    matched_main: list[str] = Field(default_factory=list)
    matched_optional: list[str] = Field(default_factory=list)
    missing_main: list[str] = Field(default_factory=list)


class RecipeCandidate(BaseModel):
    rank: int
    menu_no: str
    name: str
    category: str
    cook_minutes: int
    reservation_ok: bool
    mixer_required: bool
    serves: int
    score: float = Field(..., description="0〜100 の総合スコア (高いほど推奨度大)")
    ingredient_match: IngredientMatch
    rationale: list[str] = Field(default_factory=list, description="人間可読な根拠")
    skill_tags: list[str] = Field(default_factory=list)
    official_source: str
    verified: bool = False


class SuggestResponse(BaseModel):
    suggested_at: datetime
    total_scanned: int
    candidates: list[RecipeCandidate]
    fallback_hint: str | None = Field(
        default=None,
        description=(
            "ホットクック対応メニューに該当が無かった場合のヒント "
            "(例: '今回の食材ではホットクックよりフライパン調理が向いています')"
        ),
    )
    disclaimer: str = (
        "メニュー番号・調理時間はシャープ公式情報を参考にしています。"
        "実際の調理は本体液晶 / COCORO KITCHEN アプリの最新表示を優先してください。"
    )


# ---------------------------------------------------------------------------
# Inventory (Phase 2 で本格化、Phase 1 は基本 CRUD のみ)
# ---------------------------------------------------------------------------


class InventoryItem(BaseModel):
    id: int | None = None
    name: str = Field(..., min_length=1)
    quantity: float = Field(default=1, ge=0)
    unit: str = Field(default="個")
    location: Literal["fridge", "freezer", "pantry"] = Field(default="fridge")
    expires_on: str | None = Field(
        default=None,
        description="ISO 日付 (YYYY-MM-DD)。None なら期限不明",
    )
    note: str | None = None
    updated_at: datetime | None = None


class InventoryListResponse(BaseModel):
    items: list[InventoryItem]
    total: int
