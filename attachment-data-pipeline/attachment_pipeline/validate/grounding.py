"""型別接地 (typed grounding) と正規化・数値再検証。

設計ガイド 4.5 の核。LLM が返した値を **コードで原文へ逆引き** し、原文に位置特定
できない値は捏造として棄却する。数値・日付は「原文側・値側の双方を正規化して突合」
することで H1 (verbatim↔正規化の衝突) と部分一致罠 (18800→800) の双方を処理する。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from ..schema import FieldType

# 全角→半角 (長さ保存。オフセットがずれない)。
_ZEN2HAN = str.maketrans("０１２３４５６７８９，．－％", "0123456789,.-%")

# 金額スケール単位。長いものから順に判定する (百万円 を 円 より先に)。
_SCALE_UNITS: tuple[tuple[str, float], ...] = (
    ("百万円", 1e6),
    ("億円", 1e8),
    ("千円", 1e3),
    ("万円", 1e4),
    ("円", 1.0),
    ("%", 1.0),
)
_UNIT_ALT = "|".join(re.escape(u) for u, _ in _SCALE_UNITS)
# 符号(△▲) + 数字 + 任意のスケール単位 を 1 トークンとして捕捉する。
# 数値だけを切り出すと「1,200百万円」を 1200 と誤読するため、単位込みで照合する。
_NUM_TOKEN = re.compile(rf"(?<![0-9.])[△▲]?[0-9][0-9,]*(?:\.[0-9]+)?(?:{_UNIT_ALT})?")
_DATE_PATTERNS = [
    re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日"),
    re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"),
    re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})"),
]

_NAME_THRESHOLD = 90.0
_ADDRESS_THRESHOLD = 85.0


@dataclass(frozen=True)
class GroundResult:
    """接地結果。"""

    found: bool
    start: int | None = None
    end: int | None = None
    ambiguous: bool = False
    canonical: str | None = None  # 正規化済みの最終値 (採用時に出力する)


_NOT_FOUND = GroundResult(found=False)
_AMBIGUOUS = GroundResult(found=False, ambiguous=True)


def normalize_amount(s: str) -> float | None:
    """金額・数量を数値へ正規化する。

    対応: 全角、カンマ・通貨記号、スケール単位 (百万円/億円/千円/万円/円)、
    パーセント、△▲ および () による負数。財務資料のスケール (百万円→1e6 等) を
    畳み込んで実数の絶対値を返すため、`1,200百万円` と `1200000000` は一致する。
    請求書のように単位を持たない値はスケール 1 でそのまま扱う (後方互換)。
    """
    h = s.translate(_ZEN2HAN).strip()
    if not h:
        return None
    neg = False
    if h[0] in "△▲":
        neg, h = True, h[1:]
    elif h.startswith("(") and h.endswith(")"):
        neg, h = True, h[1:-1]
    scale = 1.0
    for unit, sc in _SCALE_UNITS:
        if h.endswith(unit):
            scale, h = sc, h[: -len(unit)]
            break
    h = re.sub(r"[¥￥$,\s]", "", h)
    if not re.fullmatch(r"\d+(?:\.\d+)?", h):
        return None
    v = float(h) * scale
    return -v if neg else v


def canonical_number(v: float) -> str:
    """正規化済み数値を比較・出力用の文字列に整える (整数なら小数点を付けない)。"""
    if float(v).is_integer():
        return str(int(v))
    return str(round(v, 6))


def normalize_date(s: str) -> str | None:
    """実在する日付なら ISO (YYYY-MM-DD) を返す。不正な日付は None。"""
    h = s.translate(_ZEN2HAN)
    for pat in _DATE_PATTERNS:
        m = pat.search(h)
        if m:
            y, mo, d = (int(g) for g in m.groups())
            if not (1 <= mo <= 12 and 1 <= d <= _days_in_month(y, mo)):
                return None
            return f"{y:04d}-{mo:02d}-{d:02d}"
    return None


def _days_in_month(year: int, month: int) -> int:
    if month == 2:
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        return 29 if leap else 28
    return 30 if month in (4, 6, 9, 11) else 31


def _evidence_region(text: str, evidence_span: str) -> tuple[int, int] | None:
    if not evidence_span:
        return None
    idx = text.find(evidence_span)
    if idx == -1:
        return None
    return idx, idx + len(evidence_span)


def _pick(
    candidates: list[tuple[int, int]], region: tuple[int, int] | None, canonical: str
) -> GroundResult:
    """候補から evidence 領域で一意化し接地位置を決める。

    候補は呼び出し側で「正規化値が target に一致するもの」だけに絞り込まれている
    (数値: int 等価 / 日付: ISO 等価 / コード・名称: 文字列等価)。したがって **どの
    候補位置を選んでも出力 canonical は同一** であり、位置の曖昧さは値の precision を
    脅かさない (スロット取り違えはラベル帰属チェックが別途守る)。よって複数該当でも
    棄却せず、evidence 領域内を優先して 1 つ選ぶ。逆引き不能 (候補ゼロ) のみ棄却。
    """
    if not candidates:
        return _NOT_FOUND
    scoped = candidates
    if region is not None:
        rs, re_ = region
        inside = [c for c in candidates if rs <= c[0] and c[1] <= re_]
        if inside:
            scoped = inside
    chosen = scoped[0]
    return GroundResult(True, chosen[0], chosen[1], canonical=canonical)


def ground_numeric(value: str, text: str, evidence_span: str) -> GroundResult:
    target = normalize_amount(value)
    if target is None:
        return _NOT_FOUND
    hw = text.translate(_ZEN2HAN)
    candidates: list[tuple[int, int]] = []
    for m in _NUM_TOKEN.finditer(hw):
        cand = normalize_amount(m.group())
        if cand is not None and math.isclose(cand, target, rel_tol=1e-9, abs_tol=1e-6):
            candidates.append((m.start(), m.end()))
    return _pick(candidates, _evidence_region(text, evidence_span), canonical_number(target))


def ground_date(value: str, text: str, evidence_span: str) -> GroundResult:
    iso = normalize_date(value)
    if iso is None:
        return _NOT_FOUND
    hw = text.translate(_ZEN2HAN)
    candidates: list[tuple[int, int]] = []
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(hw):
            if normalize_date(m.group()) == iso:
                candidates.append((m.start(), m.end()))
    return _pick(candidates, _evidence_region(text, evidence_span), iso)


def ground_exact(value: str, text: str, evidence_span: str) -> GroundResult:
    if not value:
        return _NOT_FOUND
    candidates: list[tuple[int, int]] = []
    idx = text.find(value)
    while idx != -1:
        candidates.append((idx, idx + len(value)))
        idx = text.find(value, idx + 1)
    return _pick(candidates, _evidence_region(text, evidence_span), value)


def ground_fuzzy(value: str, text: str, evidence_span: str, threshold: float) -> GroundResult:
    if not value:
        return _NOT_FOUND
    # 完全一致が取れれば最優先。
    exact = ground_exact(value, text, evidence_span)
    if exact.found:
        return exact
    region = _evidence_region(text, evidence_span)
    rs, re_ = region if region else (0, len(text))
    window = text[rs:re_]
    n = len(value)
    best_score = 0.0
    best: tuple[int, int] | None = None
    for i in range(0, max(1, len(window) - n + 1)):
        for span_len in (n, n + 1, n - 1):
            if span_len <= 0 or i + span_len > len(window):
                continue
            cand = window[i : i + span_len]
            score = fuzz.ratio(value, cand)
            if score > best_score:
                best_score = score
                best = (rs + i, rs + i + span_len)
    if best is not None and best_score >= threshold:
        return GroundResult(True, best[0], best[1], canonical=text[best[0] : best[1]])
    return _NOT_FOUND


def ground(field_type: FieldType, value: str, text: str, evidence_span: str) -> GroundResult:
    """型に応じた接地戦略をディスパッチ。"""
    if field_type in (FieldType.AMOUNT, FieldType.NUMERIC):
        return ground_numeric(value, text, evidence_span)
    if field_type is FieldType.DATE:
        return ground_date(value, text, evidence_span)
    if field_type is FieldType.CODE:
        return ground_exact(value, text, evidence_span)
    if field_type is FieldType.NAME:
        return ground_fuzzy(value, text, evidence_span, _NAME_THRESHOLD)
    if field_type is FieldType.ADDRESS:
        return ground_fuzzy(value, text, evidence_span, _ADDRESS_THRESHOLD)
    return _NOT_FOUND
