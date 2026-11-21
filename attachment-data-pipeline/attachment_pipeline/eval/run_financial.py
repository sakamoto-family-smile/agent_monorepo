"""財務資料 (有価証券報告書) ドメインの精度検証ハーネス。

``python -m attachment_pipeline.eval.run_financial`` で実行。
請求書版と同じく「抽出のみ(baseline)」と「抽出+検証」を比較し、財務固有の誤り
(スケール忘れ/符号反転/当期前期取り違え) を検証層が弾けるかを定量化する。
"""

from __future__ import annotations

from ..contracts import DecidedField, Decision, ExtractionResult
from ..extract.financial_mock import FinancialInjectionConfig, FinancialMockExtractor
from ..schema_financial import FINANCIAL_LABELS
from ..synth.financial import generate_dataset
from ..synth.generator import GoldSample
from ..validate.decide import ValidationConfig, validate_results
from .metrics import canonicalize, compute_metrics

DEV_RANGE = (0, 70)
TEST_RANGE = (70, 100)


def _baseline_decisions(extractions: list[ExtractionResult]) -> list[DecidedField]:
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


def run(samples: list[GoldSample], extractor: FinancialMockExtractor, tau: float):
    base_items, val_items = [], []
    cfg = ValidationConfig(tau=tau)
    for s in samples:
        exts = extractor.extract(s)
        base_items.append((s, exts, _baseline_decisions(exts)))
        val_items.append((s, exts, validate_results(exts, s.text, cfg, FINANCIAL_LABELS)))
    return base_items, val_items


def main() -> None:
    test = generate_dataset(*TEST_RANGE)
    extractor = FinancialMockExtractor(FinancialInjectionConfig())

    print("=" * 78)
    print("精度検証 (財務/有価証券報告書): 『抽出のみ』vs『抽出+検証』")
    print(f"test={len(test)}件 / τ=0.5 / 誤り: scale_drop/sign_flip/wrong_period 等")
    print("=" * 78)

    base_items, val_items = run(test, extractor, tau=0.5)
    base_m = compute_metrics("抽出のみ(baseline)", base_items)
    val_m = compute_metrics("抽出+検証(grounding+帰属+τ)", val_items)
    print(base_m.summary())
    print(val_m.summary())
    if val_m.missed_errors:
        print(f"  ⚠ 見逃した誤採用: {val_m.missed_errors[:10]}")
    else:
        print("  ✓ 検証層をすり抜けた誤採用(FP) = 0")

    print("\n--- risk–coverage 掃引 (test, τを変化) ---")
    print(f"{'τ':>6} {'precision':>10} {'coverage':>9} {'recall':>8} {'FP':>4}")
    for tau in (0.0, 0.3, 0.5, 0.7, 0.9, 0.95):
        _, items = run(test, extractor, tau=tau)
        m = compute_metrics(f"τ={tau}", items)
        print(
            f"{tau:>6.2f} {m.precision:>10.3f} {m.coverage:>9.3f} "
            f"{m.recall:>8.3f} {m.false_positive:>4}"
        )

    print("\n--- clean抽出器 (誤りなし) の健全性確認 ---")
    clean = FinancialMockExtractor(FinancialInjectionConfig.clean())
    _, clean_items = run(test, clean, tau=0.5)
    print(compute_metrics("clean", clean_items).summary())


if __name__ == "__main__":
    main()
