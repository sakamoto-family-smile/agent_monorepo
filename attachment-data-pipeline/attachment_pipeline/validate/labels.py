"""ラベル辞書とラベル帰属チェック (C2: スロット帰属ミス対策)。

gold には依存せず、**原文からラベルキーワードを再検出** して、ある値の接地位置の
直前ラベルが、そのフィールドの正当な所有者かを判定する。issuer↔recipient 入替や、
財務資料の 当期↔前期 列取り違えのように、両方の値が原文に実在するケースは接地だけ
では防げないため帰属で捕捉する。

ラベル辞書 (lexicon) はドメインごとに異なるため注入可能にしている。デフォルトは
請求書ドメインの ``INVOICE_LABELS``。
"""

from __future__ import annotations

from dataclasses import dataclass

LabelLexicon = dict[str, frozenset[str]]

# 請求書ドメインの既定 lexicon (ラベル文字列 → 正当に後続するフィールドID集合)。
INVOICE_LABELS: LabelLexicon = {
    "請求書番号": frozenset({"invoice_no"}),
    "発行日": frozenset({"issue_date"}),
    "お支払期限": frozenset({"due_date"}),
    "請求先": frozenset({"recipient_name"}),
    "発行元": frozenset({"issuer_name", "issuer_address"}),
    "小計": frozenset({"subtotal"}),
    "消費税": frozenset({"tax"}),
    "合計": frozenset({"total"}),
}

# 後方互換のための別名 (旧コードが参照)。
LABEL_OWNERS = INVOICE_LABELS


@dataclass(frozen=True)
class _Occ:
    start: int
    owners: frozenset[str]


def labeled_fields(lexicon: LabelLexicon) -> frozenset[str]:
    """lexicon でいずれかのラベルに所有される (= 帰属チェック対象の) フィールド集合。"""
    if not lexicon:
        return frozenset()
    return frozenset().union(*lexicon.values())


def find_label_occurrences(text: str, lexicon: LabelLexicon | None = None) -> list[_Occ]:
    """原文中の全ラベル出現を開始位置順で返す。"""
    lex = INVOICE_LABELS if lexicon is None else lexicon
    occs: list[_Occ] = []
    for label, owners in lex.items():
        idx = text.find(label)
        while idx != -1:
            occs.append(_Occ(idx, owners))
            idx = text.find(label, idx + 1)
    occs.sort(key=lambda o: o.start)
    return occs


def attribution_ok(
    field_id: str,
    grounded_start: int,
    occs: list[_Occ],
    labeled: frozenset[str],
) -> bool:
    """接地位置の直前ラベルが field_id を所有していれば True。

    - 帰属対象外フィールド (ラベルを持たない明細など) は常に True。
    - 直前にラベルが無い場合も True (過剰棄却を避ける)。
    - 直前ラベルが別フィールドの所有 → False (スロット取り違えの疑い)。
    """
    if field_id not in labeled:
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
