"""実 LLM 抽出器での精度検証ハーネス (財務ドメイン)。

``python -m attachment_pipeline.eval.run_llm`` で実行。実モデルの素の抽出を
「抽出のみ(baseline)」とし、検証層を通した「抽出+検証」と precision を比較する。
モックと違い、実モデルの取りこぼし・誤読など『本物の誤り分布』に対して検証層の
上積みを測れる。

認証 (ANTHROPIC_API_KEY 等) が無い環境では、その旨を表示して終了する。
"""

from __future__ import annotations

import os
import sys

from ..contracts import DecidedField
from ..extract.llm_extractor import FieldSpec, LLMExtractor, build_anthropic_client
from ..schema_financial import FINANCIAL_FIELD_TYPES, FINANCIAL_LABELS
from ..synth.financial import generate_dataset
from ..synth.financial_long import generate_long_dataset
from ..synth.generator import GoldSample
from ..validate.decide import ValidationConfig, validate_results
from .metrics import canonicalize, compute_metrics
from .run_financial import _baseline_decisions

# field_id → ラベル (説明文)。全ラベルが単一フィールド所有なので逆引きできる。
_LABEL_OF = {next(iter(o)): label for label, o in FINANCIAL_LABELS.items()}


def financial_specs() -> list[FieldSpec]:
    return [
        FieldSpec(fid, ftype, _LABEL_OF.get(fid, fid))
        for fid, ftype in FINANCIAL_FIELD_TYPES.items()
    ]


def run_llm(samples: list[GoldSample], extractor: LLMExtractor, tau: float):
    base_items, val_items = [], []
    cfg = ValidationConfig(tau=tau)
    for s in samples:
        exts = extractor.extract(s)
        base_items.append((s, exts, _baseline_decisions(exts)))
        val_items.append((s, exts, validate_results(exts, s.text, cfg, FINANCIAL_LABELS)))
    return base_items, val_items


def main() -> None:
    n = int(os.environ.get("LLM_EVAL_N", "10"))
    long = os.environ.get("LLM_EVAL_LONG", "") == "1"
    model = os.environ.get("LLM_EVAL_MODEL", "claude-haiku-4-5-20251001")

    try:
        client = build_anthropic_client(model=model)
    except RuntimeError as e:
        print(f"[skip] 実 LLM を呼べません: {e}")
        print("ANTHROPIC_API_KEY を設定して再実行してください。")
        sys.exit(0)

    samples = (
        generate_long_dataset(70, 70 + n) if long else generate_dataset(70, 70 + n)
    )
    extractor = LLMExtractor(client, financial_specs())

    print("=" * 78)
    print(f"精度検証 (実LLM={model}, 財務{'/長文' if long else ''}): 抽出のみ vs 抽出+検証")
    print(f"n={len(samples)} / τ=0.5")
    print("=" * 78)

    base_items, val_items = run_llm(samples, extractor, tau=0.5)
    print(compute_metrics("抽出のみ(LLM baseline)", base_items).summary())
    val_m = compute_metrics("抽出+検証", val_items)
    print(val_m.summary())
    if val_m.missed_errors:
        print(f"  ⚠ 見逃した誤採用: {val_m.missed_errors[:10]}")


# 採点を外部 (Claude 本人による抽出など) から再現するためのユーティリティ。
def score_extractions(
    sample: GoldSample, extractions: list, tau: float = 0.5
) -> tuple[DecidedField, ...]:
    cfg = ValidationConfig(tau=tau)
    return tuple(validate_results(extractions, sample.text, cfg, FINANCIAL_LABELS))


__all__ = ["financial_specs", "run_llm", "score_extractions", "canonicalize"]


if __name__ == "__main__":
    main()
