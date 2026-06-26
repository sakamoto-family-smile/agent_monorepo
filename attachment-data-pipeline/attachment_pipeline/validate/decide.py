"""検証チェーンと最終採否ロジック (decide_field)。

関門の順序 (設計ガイド 4.5.7): 接地(+数値再検証は接地に内包) → 帰属 → 確信度(τ)。
いずれの関門も失敗は null へ落とす。reject (誤りと判定) と abstain (確信度不足) を
区別して記録する ── abstain は後段 ReCoVERR で復活余地があるため。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts import CharInterval, DecidedField, Decision, ExtractionResult
from .grounding import ground
from .labels import (
    INVOICE_LABELS,
    LabelLexicon,
    attribution_ok,
    find_label_occurrences,
    labeled_fields,
)

_DEFAULT_TAU = 0.5


@dataclass(frozen=True)
class ValidationConfig:
    tau: float = _DEFAULT_TAU


def decide_field(
    result: ExtractionResult,
    text: str,
    label_occs: list,
    config: ValidationConfig,
    labeled: frozenset[str],
) -> DecidedField:
    votes: list[str] = []

    # ①+② 接地 (型別) + 数値再検証 (int 等価で内包)。
    g = ground(result.field_type, result.value, text, result.evidence_span)
    if not g.found:
        votes.append("ground:ambiguous" if g.ambiguous else "ground:not_found")
        return DecidedField(result.field_id, None, None, 0.0, Decision.REJECT, votes)
    votes.append("ground:ok")
    interval = CharInterval(g.start, g.end)  # type: ignore[arg-type]

    # ③ 帰属チェック (C2: スロット取り違え)。
    if not attribution_ok(result.field_id, g.start, label_occs, labeled):  # type: ignore[arg-type]
        votes.append("attribution:reject")
        return DecidedField(result.field_id, None, interval, 0.0, Decision.REJECT, votes)
    votes.append("attribution:ok")

    # ④ 確信度 τ (v1 は校正なし。extract_conf をそのまま使う)。
    if result.extract_conf < config.tau:
        votes.append("confidence:abstain")
        return DecidedField(
            result.field_id, None, interval, result.extract_conf, Decision.ABSTAIN, votes
        )
    votes.append("confidence:ok")

    return DecidedField(
        result.field_id,
        g.canonical,
        interval,
        result.extract_conf,
        Decision.ACCEPT,
        votes,
    )


def validate_results(
    results: list[ExtractionResult],
    text: str,
    config: ValidationConfig | None = None,
    label_lexicon: LabelLexicon | None = None,
) -> list[DecidedField]:
    """ExtractionResult[] を検証して DecidedField[] にする。

    label_lexicon でドメインのラベル辞書を注入する (既定は請求書)。
    """
    cfg = config or ValidationConfig()
    lexicon = INVOICE_LABELS if label_lexicon is None else label_lexicon
    occs = find_label_occurrences(text, lexicon)
    labeled = labeled_fields(lexicon)
    return [decide_field(r, text, occs, cfg, labeled) for r in results]
