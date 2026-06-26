"""ラベル辞書とラベル帰属チェック (C2: スロット帰属ミス対策)。

gold には依存せず、**原文からラベルキーワードを再検出** して、ある値の接地位置の
直前ラベルが、そのフィールドの正当な所有者かを判定する。issuer↔recipient 入替の
ように両値が原文に実在するケースを、接地だけでは防げないため帰属で捕捉する。
"""

from __future__ import annotations

from dataclasses import dataclass

# ラベル文字列 → そのラベル直後に正当に現れるフィールドID集合。
LABEL_OWNERS: dict[str, frozenset[str]] = {
    "請求書番号": frozenset({"invoice_no"}),
    "発行日": frozenset({"issue_date"}),
    "お支払期限": frozenset({"due_date"}),
    "請求先": frozenset({"recipient_name"}),
    "発行元": frozenset({"issuer_name", "issuer_address"}),
    "小計": frozenset({"subtotal"}),
    "消費税": frozenset({"tax"}),
    "合計": frozenset({"total"}),
}

# 何らかのラベルに所有される (= 帰属チェック対象の) フィールド。
LABELED_FIELDS: frozenset[str] = frozenset().union(*LABEL_OWNERS.values())


@dataclass(frozen=True)
class _Occ:
    start: int
    owners: frozenset[str]


def find_label_occurrences(text: str) -> list[_Occ]:
    """原文中の全ラベル出現を開始位置順で返す。"""
    occs: list[_Occ] = []
    for label, owners in LABEL_OWNERS.items():
        idx = text.find(label)
        while idx != -1:
            occs.append(_Occ(idx, owners))
            idx = text.find(label, idx + 1)
    occs.sort(key=lambda o: o.start)
    return occs


def attribution_ok(field_id: str, grounded_start: int, occs: list[_Occ]) -> bool:
    """接地位置の直前ラベルが field_id を所有していれば True。

    - 帰属対象外フィールド (ラベルを持たない明細など) は常に True。
    - 直前にラベルが無い場合も True (過剰棄却を避ける)。
    - 直前ラベルが別フィールドの所有 → False (スロット取り違えの疑い)。
    """
    if field_id not in LABELED_FIELDS:
        return True
    nearest: _Occ | None = None
    for o in occs:
        if o.start <= grounded_start:
            nearest = o
        else:
            break
    if nearest is None:
        return True
    return field_id in nearest.owners
