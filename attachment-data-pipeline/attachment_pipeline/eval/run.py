"""精度検証ハーネス (Step 4: 抽出と検証の統合)。

``python -m attachment_pipeline.eval.run`` で実行。
誤り注入Mockに対し「検証なし(ベースライン)」と「検証あり」の precision を比較し、
検証層が誤採用(FP)をどれだけ削減できるかを定量化する。さらに τ を掃引して
risk–coverage を表示する。
"""

from __future__ import annotations

from ..contracts import DecidedField, Decision, ExtractionResult
from ..extract.mock_extractor import InjectionConfig, MockExtractor
from ..synth.generator import GoldSample, generate_dataset
from ..validate.decide import ValidationConfig, validate_results
from .metrics import canonicalize, compute_metrics

DEV_RANGE = (0, 70)
TEST_RANGE = (70, 100)


def _baseline_decisions(extractions: list[ExtractionResult]) -> list[DecidedField]:
    """検証なし: 抽出値をそのまま (正規化のみして) 全採用する。"""
    out: list[DecidedField] = []
    for e in extractions:
        canon = canonicalize(e.field_type, e.value)
        out.append(
            DecidedField(
                e.field_id,
                canon if canon is not None else e.value,
                None,
                e.extract_conf,
                Decision.ACCEPT,
                ["baseline:accept"],
            )
        )
    return out


def _run(
    samples: list[GoldSample], extractor: MockExtractor, tau: float
) -> tuple[list, list]:
    baseline_items = []
    validated_items = []
    cfg = ValidationConfig(tau=tau)
    for s in samples:
        exts = extractor.extract(s)
        baseline_items.append((s, exts, _baseline_decisions(exts)))
        validated_items.append((s, exts, validate_results(exts, s.text, cfg)))
    return baseline_items, validated_items


def main() -> None:
    dev = generate_dataset(*DEV_RANGE)
    test = generate_dataset(*TEST_RANGE)
    extractor = MockExtractor(InjectionConfig())

    print("=" * 78)
    print("精度検証: 誤り注入Mock抽出器に対する『検証なし』vs『検証あり』")
    print(f"dev={len(dev)}件 / test={len(test)}件 / τ=0.5")
    print("=" * 78)

    base_items, val_items = _run(test, extractor, tau=0.5)
    base_m = compute_metrics("検証なし(baseline)", base_items)
    val_m = compute_metrics("検証あり(grounding+帰属+τ)", val_items)
    print(base_m.summary())
    print(val_m.summary())
    if val_m.missed_errors:
        print(f"  ⚠ 見逃した誤採用: {val_m.missed_errors[:10]}")
    else:
        print("  ✓ 検証層をすり抜けた誤採用(FP) = 0")

    print("\n--- risk–coverage 掃引 (test, τを変化) ---")
    print(f"{'τ':>6} {'precision':>10} {'coverage':>9} {'recall':>8} {'FP':>4}")
    for tau in (0.0, 0.3, 0.5, 0.7, 0.9, 0.95):
        _, items = _run(test, extractor, tau=tau)
        m = compute_metrics(f"τ={tau}", items)
        print(
            f"{tau:>6.2f} {m.precision:>10.3f} {m.coverage:>9.3f} "
            f"{m.recall:>8.3f} {m.false_positive:>4}"
        )

    print("\n--- 誤りモード別 (clean抽出器=誤りなしの健全性確認) ---")
    clean = MockExtractor(InjectionConfig.clean())
    _, clean_items = _run(test, clean, tau=0.5)
    clean_m = compute_metrics("clean", clean_items)
    print(clean_m.summary())


if __name__ == "__main__":
    main()
