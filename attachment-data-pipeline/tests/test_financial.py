"""財務資料 (有価証券報告書) ドメインの精度テスト。

スケール (百万円)・符号 (△)・当期/前期 列取り違え という財務固有の誤りを、
検証層 (スケール対応接地 + ラベル帰属) が捕捉できることを回帰ゲート化する。
"""

from __future__ import annotations

from attachment_pipeline.contracts import Decision
from attachment_pipeline.eval.metrics import compute_metrics, gold_canonical
from attachment_pipeline.eval.run_financial import run
from attachment_pipeline.extract.financial_mock import (
    FinancialInjectionConfig,
    FinancialMockExtractor,
)
from attachment_pipeline.schema import FieldType
from attachment_pipeline.schema_financial import FINANCIAL_LABELS
from attachment_pipeline.synth.financial import generate_dataset, generate_sample
from attachment_pipeline.validate.decide import ValidationConfig, validate_results
from attachment_pipeline.validate.grounding import (
    canonical_number,
    ground,
    normalize_amount,
)

_TEST = generate_dataset(70, 100)


def _only(**kwargs) -> FinancialInjectionConfig:
    """指定モードだけを確率1.0、他を0にした設定。"""
    base = dict(
        normalized=0.0, scale_drop=0.0, sign_flip=0.0, wrong_period=0.0,
        substring_trap=0.0, hallucination=0.0, low_conf=0.0,
    )
    base.update(kwargs)
    return FinancialInjectionConfig(**base)


# ── 正規化・接地 (スケール/符号) ─────────────────────────────
def test_scale_and_sign_normalization():
    assert normalize_amount("1,495,000百万円") == 1_495_000_000_000
    assert normalize_amount("△12,345百万円") == -12_345_000_000
    assert normalize_amount("42.3%") == 42.3
    assert normalize_amount("80.91円") == 80.91
    assert canonical_number(1_495_000_000_000.0) == "1495000000000"


def test_scale_aware_grounding():
    text = "当期売上高: 1,495,000百万円"
    # 単位込みで一致 → 接地成功
    g = ground(FieldType.AMOUNT, "1,495,000百万円", text, text)
    assert g.found and g.canonical == "1495000000000"
    # 単位を落とした値 (=1,495,000円) は百万円スケールのトークンに一致せず棄却
    g2 = ground(FieldType.AMOUNT, "1,495,000", text, text)
    assert g2.found is False


# ── 生成器の健全性 ──────────────────────────────────────────
def test_generator_spans_intact():
    s = generate_sample(70)
    for fid, (a, b) in s.spans.items():
        assert s.text[a:b] == s.gold_value(fid)
    assert gold_canonical(s, "net_sales_current").isdigit()


# ── 誤りモード別の捕捉 ──────────────────────────────────────
def test_scale_drop_rejected_and_no_false_accept():
    _, val = run(_TEST, FinancialMockExtractor(_only(scale_drop=1.0)), tau=0.5)
    m = compute_metrics("scale_drop", val)
    assert m.false_positive == 0
    # 金額フィールドは単位欠落で接地失敗 → reject されている
    assert m.n_reject > 0


def test_sign_flip_no_false_accept():
    _, val = run(_TEST, FinancialMockExtractor(_only(sign_flip=1.0)), tau=0.5)
    m = compute_metrics("sign_flip", val)
    assert m.false_positive == 0


def test_wrong_period_rejected_by_attribution():
    extractor = FinancialMockExtractor(_only(wrong_period=1.0))
    hit = False
    for s in _TEST:
        exts = extractor.extract(s)
        ds = {d.field_id: d for d in validate_results(exts, s.text, ValidationConfig(0.5), FINANCIAL_LABELS)}
        d = ds["net_sales_current"]
        # 当期に前期の値が入った場合、帰属チェックで reject されるはず
        if d.decision is Decision.REJECT:
            hit = True
            assert "attribution:reject" in d.validator_votes
    assert hit


# ── 統合: precision優先要件 ─────────────────────────────────
def test_validation_eliminates_false_accepts_financial():
    _, val = run(_TEST, FinancialMockExtractor(FinancialInjectionConfig()), tau=0.5)
    m = compute_metrics("validated", val)
    assert m.false_positive == 0
    assert m.precision == 1.0


def test_validation_beats_baseline_financial():
    base, val = run(_TEST, FinancialMockExtractor(FinancialInjectionConfig()), tau=0.5)
    bm = compute_metrics("baseline", base)
    vm = compute_metrics("validated", val)
    assert bm.false_positive > 0
    assert vm.precision > bm.precision


def test_clean_extractor_no_false_rejects_financial():
    _, val = run(_TEST, FinancialMockExtractor(FinancialInjectionConfig.clean()), tau=0.5)
    m = compute_metrics("clean", val)
    assert m.false_positive == 0
    assert m.false_reject == 0
    assert m.coverage == 1.0
