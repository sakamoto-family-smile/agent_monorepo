"""gold 突合による精度指標の算出。

正解は gold record の正規形 (canonical)。パイプライン出力 (DecidedField) の採用値が
canonical と一致すれば正採用(TP)、不一致採用は誤採用(FP=precisionの敵)。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts import DecidedField, Decision, ExtractionResult
from ..schema import FieldType, field_type_of
from ..synth.generator import GoldSample
from ..validate.grounding import normalize_amount, normalize_date


def canonicalize(field_type: FieldType, value: str) -> str | None:
    """接地が出力する canonical と同じ正規形に値を寄せる。"""
    if field_type in (FieldType.AMOUNT, FieldType.NUMERIC):
        n = normalize_amount(value)
        return str(n) if n is not None else None
    if field_type is FieldType.DATE:
        return normalize_date(value)
    return value.strip()


def gold_canonical(sample: GoldSample, field_id: str) -> str | None:
    ftype = field_type_of(field_id)
    return canonicalize(ftype, sample.gold_value(field_id))


@dataclass
class Metrics:
    """評価結果。"""

    label: str
    n_fields: int = 0
    n_accept: int = 0
    n_reject: int = 0
    n_abstain: int = 0
    true_positive: int = 0  # 正しく採用
    false_positive: int = 0  # 誤って採用 (precision の敵)
    n_erroneous_extractions: int = 0  # 抽出が誤っていたフィールド数
    errors_caught: int = 0  # うち、採用を回避できた数
    n_correct_extractions: int = 0  # 抽出が正しかったフィールド数
    correct_accepted: int = 0  # うち、正しく採用できた数
    false_reject: int = 0  # 正しい抽出を誤って reject した数
    missed_errors: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.missed_errors is None:
            self.missed_errors = []

    @property
    def precision(self) -> float:
        return self.true_positive / self.n_accept if self.n_accept else 1.0

    @property
    def coverage(self) -> float:
        return self.n_accept / self.n_fields if self.n_fields else 0.0

    @property
    def recall(self) -> float:
        return (
            self.correct_accepted / self.n_correct_extractions
            if self.n_correct_extractions
            else 1.0
        )

    @property
    def error_catch_rate(self) -> float:
        return (
            self.errors_caught / self.n_erroneous_extractions
            if self.n_erroneous_extractions
            else 1.0
        )

    def summary(self) -> str:
        return (
            f"[{self.label}] "
            f"precision={self.precision:.3f} coverage={self.coverage:.3f} "
            f"recall={self.recall:.3f} | "
            f"FP(誤採用)={self.false_positive} "
            f"誤り捕捉={self.errors_caught}/{self.n_erroneous_extractions} "
            f"({self.error_catch_rate:.3f}) "
            f"過棄却={self.false_reject} "
            f"accept/reject/abstain={self.n_accept}/{self.n_reject}/{self.n_abstain}"
        )


def compute_metrics(
    label: str,
    items: list[tuple[GoldSample, list[ExtractionResult], list[DecidedField]]],
) -> Metrics:
    m = Metrics(label=label)
    for sample, extractions, decisions in items:
        ext_by_id = {e.field_id: e for e in extractions}
        for d in decisions:
            m.n_fields += 1
            gold = gold_canonical(sample, d.field_id)
            ext = ext_by_id.get(d.field_id)
            ftype = field_type_of(d.field_id)
            ext_canon = canonicalize(ftype, ext.value) if ext else None
            extraction_correct = ext_canon is not None and ext_canon == gold

            if extraction_correct:
                m.n_correct_extractions += 1
            else:
                m.n_erroneous_extractions += 1

            if d.decision is Decision.ACCEPT:
                m.n_accept += 1
                if d.value == gold:
                    m.true_positive += 1
                    if extraction_correct:
                        m.correct_accepted += 1
                else:
                    m.false_positive += 1
                    if not extraction_correct:
                        m.missed_errors.append(f"{sample.sample_id}:{d.field_id}={d.value!r}")
            else:
                if d.decision is Decision.REJECT:
                    m.n_reject += 1
                else:
                    m.n_abstain += 1
                if not extraction_correct:
                    m.errors_caught += 1
                else:
                    m.false_reject += 1
    return m
