"""長文 (実物スケール) 財務資料での精度検証ハーネス (option 2)。

``python -m attachment_pipeline.eval.run_financial_long`` で実行。
数万字・撹乱テーブル (数値衝突) 入りの有報で「抽出のみ vs 抽出+検証」を比較し、
逆引きの曖昧性が増えても precision が保たれるかを確認する。チャンク分割の統計も表示。
"""

from __future__ import annotations

from statistics import mean

from ..extract.financial_mock import FinancialInjectionConfig, FinancialMockExtractor
from ..synth.financial_long import generate_long_dataset
from ..validate.chunking import chunk_text
from .metrics import compute_metrics
from .run_financial import run

TEST_RANGE = (70, 100)
TARGET_CHARS = 20000


def main() -> None:
    test = generate_long_dataset(*TEST_RANGE, target_chars=TARGET_CHARS)
    lengths = [len(s.text) for s in test]
    chunks_per_doc = [len(chunk_text(s.text)) for s in test]

    print("=" * 78)
    print("精度検証 (長文/実物スケール有報): 『抽出のみ』vs『抽出+検証』")
    print(
        f"test={len(test)}件 / 文字数 平均{mean(lengths):.0f} "
        f"(min{min(lengths)}-max{max(lengths)}) / チャンク平均{mean(chunks_per_doc):.1f}個"
    )
    print("=" * 78)

    extractor = FinancialMockExtractor(FinancialInjectionConfig())
    base_items, val_items = run(test, extractor, tau=0.5)
    print(compute_metrics("抽出のみ(baseline)", base_items).summary())
    val_m = compute_metrics("抽出+検証(grounding+帰属+τ)", val_items)
    print(val_m.summary())
    if val_m.missed_errors:
        print(f"  ⚠ 見逃した誤採用: {val_m.missed_errors[:10]}")
    else:
        print("  ✓ 撹乱テーブルの数値衝突下でも誤採用(FP) = 0")

    print("\n--- 短文版との比較 (検証層は長文ノイズに不変か) ---")
    print("  ※ mock は gold span を知るため、長文での取りこぼし(lost in the middle)は")
    print("    再現されない。長文での抽出側劣化は実 LLM 抽出器でのみ評価可能。")

    print("\n--- clean抽出器 (誤りなし) の健全性確認 ---")
    clean = FinancialMockExtractor(FinancialInjectionConfig.clean())
    _, clean_items = run(test, clean, tau=0.5)
    print(compute_metrics("clean", clean_items).summary())


if __name__ == "__main__":
    main()
