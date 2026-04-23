"""ホットクックレシピ提案エンジン (ルールベース + 任意で Claude 補強)。

Phase 1 ではルールベース ("fast" モード) を主軸にして、Claude による rationale 強化は
"agent" モードとして API レイヤから差し替えられるよう関数化しておく (実装は Phase 2 以降)。

スコアリング (0〜100点):
  - 食材マッチ率           最大 50 点
  - 主材料カバレッジ       最大 20 点
  - 調理時間 (短いほど良い) 最大 15 点
  - 予約調理可能           最大 10 点
  - まぜ技ユニット要否一致 最大  5 点 (require_no_mixer 時のみ加点)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from agents.ingredient_resolver import resolve_many
from models.menu import HotcookMenu
from models.recipe import (
    IngredientInput,
    IngredientMatch,
    RecipeCandidate,
    SuggestRequest,
    SuggestResponse,
)
from services.menu_catalog import get_all_menus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# スコア計算
# ---------------------------------------------------------------------------


def _cook_time_score(cook_minutes: int, max_cook_minutes: int | None) -> float:
    """調理時間が短いほど高得点 (15 点満点)。"""
    if cook_minutes <= 15:
        return 15.0
    if cook_minutes <= 30:
        return 12.0
    if cook_minutes <= 45:
        return 9.0
    if cook_minutes <= 60:
        return 6.0
    if cook_minutes <= 90:
        return 3.0
    return 0.0


def _ingredient_match(
    menu: HotcookMenu, available_tags: set[str], available_names: set[str]
) -> tuple[float, IngredientMatch]:
    """食材マッチ率 (50点満点) + 主材料カバレッジ (20点満点) を返す。"""
    main_tags = [t for t in menu.ingredient_tags if t]
    main_names_lower = {n.lower() for n in menu.main_ingredients}
    optional_names_lower = {n.lower() for n in menu.optional_ingredients}

    # tag ベースのマッチ (resolver で正規化されたもの)
    matched_tags = [t for t in main_tags if t in available_tags]
    tag_match_rate = (len(matched_tags) / len(main_tags)) if main_tags else 0.0

    # 名前ベースのマッチ (resolver で解決できなかった食材を救う)
    matched_main_names = sorted(main_names_lower & available_names)
    matched_optional_names = sorted(optional_names_lower & available_names)
    missing_main = sorted(main_names_lower - available_names)

    # スコア: 50 点 = tag_match_rate * 50
    score_match = tag_match_rate * 50.0

    # 主材料カバレッジボーナス (主材料 3 個中 3 個揃えば +20 点)
    if menu.main_ingredients:
        coverage = (len(menu.main_ingredients) - len(missing_main)) / len(menu.main_ingredients)
        score_coverage = coverage * 20.0
    else:
        score_coverage = 0.0

    detail = IngredientMatch(
        matched_main=matched_main_names,
        matched_optional=matched_optional_names,
        missing_main=missing_main,
    )
    return score_match + score_coverage, detail


def _build_rationale(
    menu: HotcookMenu,
    match: IngredientMatch,
    score_breakdown: dict[str, float],
) -> list[str]:
    """人間可読の根拠リスト。"""
    out: list[str] = []
    if match.matched_main:
        out.append(f"主材料 {len(match.matched_main)} 件マッチ ({', '.join(match.matched_main)})")
    if match.missing_main:
        out.append(f"不足: {', '.join(match.missing_main)}")
    if menu.cook_minutes <= 30:
        out.append(f"調理時間 {menu.cook_minutes}分 (短時間で完成)")
    elif menu.cook_minutes <= 60:
        out.append(f"調理時間 {menu.cook_minutes}分")
    else:
        out.append(f"調理時間 {menu.cook_minutes}分 (じっくり煮込み)")
    if menu.reservation_ok:
        out.append("予約調理対応 (出かける前にセット可)")
    if menu.skill_tags:
        out.append("特徴: " + " / ".join(menu.skill_tags))
    return out


# ---------------------------------------------------------------------------
# メイン関数
# ---------------------------------------------------------------------------


def suggest_recipes(req: SuggestRequest) -> SuggestResponse:
    """ルールベースでレシピを提案する。"""
    # 1) 食材を正規化
    raw_names = [i.name for i in req.ingredients]
    resolved = resolve_many(raw_names)
    available_tags: set[str] = {r.tag for r in resolved if r.tag}
    available_names: set[str] = {i.name.lower() for i in req.ingredients}

    logger.info(
        "suggest_recipes: input=%d, resolved_tags=%d, mode=%s",
        len(raw_names), len(available_tags), req.mode,
    )

    # 2) catalog を全件スキャン (Phase 1 は 30 件規模なので O(N) で十分)
    all_menus = get_all_menus()
    excluded = set(req.exclude_menu_nos)

    candidates: list[tuple[float, HotcookMenu, IngredientMatch]] = []
    for m in all_menus:
        if m.menu_no in excluded:
            continue
        if req.max_cook_minutes is not None and m.cook_minutes > req.max_cook_minutes:
            continue
        if req.require_reservation and not m.reservation_ok:
            continue
        if req.require_no_mixer and m.mixer_required:
            continue

        # マッチがゼロのメニューは候補外 (主材料が一切無いものを薦めない)
        ing_score, detail = _ingredient_match(m, available_tags, available_names)
        if not detail.matched_main and not [
            t for t in m.ingredient_tags if t in available_tags
        ]:
            continue

        time_score = _cook_time_score(m.cook_minutes, req.max_cook_minutes)
        reservation_score = 10.0 if m.reservation_ok else 0.0
        mixer_score = 5.0 if (req.require_no_mixer and not m.mixer_required) else 0.0

        total = ing_score + time_score + reservation_score + mixer_score
        candidates.append((round(total, 1), m, detail))

    candidates.sort(key=lambda x: x[0], reverse=True)

    top = candidates[: req.top_n]
    result_candidates = [
        RecipeCandidate(
            rank=i + 1,
            menu_no=m.menu_no,
            name=m.name,
            category=m.category,
            cook_minutes=m.cook_minutes,
            reservation_ok=m.reservation_ok,
            mixer_required=m.mixer_required,
            serves=m.serves,
            score=score,
            ingredient_match=detail,
            rationale=_build_rationale(m, detail, {"total": score}),
            skill_tags=m.skill_tags,
            official_source=m.official_source,
            verified=m.verified,
        )
        for i, (score, m, detail) in enumerate(top)
    ]

    fallback_hint: str | None = None
    if not result_candidates:
        fallback_hint = (
            "今回の食材ではホットクック内蔵メニューに該当が見つかりませんでした。"
            "鶏もも・玉ねぎ・じゃがいも 等の主材料が揃うと提案精度が上がります。"
        )

    return SuggestResponse(
        suggested_at=datetime.now(timezone.utc),
        total_scanned=len(all_menus),
        candidates=result_candidates,
        fallback_hint=fallback_hint,
    )


def normalize_inputs_for_history(ingredients: list[IngredientInput]) -> str:
    """suggestion_history に保存するための正規化文字列 (個人特定回避のため raw 名のみ)。"""
    return ", ".join(sorted(i.name for i in ingredients))
