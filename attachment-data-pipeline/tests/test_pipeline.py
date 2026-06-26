"""抽出→検証 統合の精度テスト (precision 優先要件の回帰ゲート)。"""

from __future__ import annotations

from attachment_pipeline.contracts import Decision
from attachment_pipeline.eval.metrics import compute_metrics
from attachment_pipeline.eval.run import _baseline_decisions
from attachment_pipeline.extract.mock_extractor import InjectionConfig, MockExtractor
from attachment_pipeline.synth.generator import generate_dataset
from attachment_pipeline.validate.decide import ValidationConfig, validate_results

_TEST = generate_dataset(70, 100)


def _items(extractor, tau):
    base, val = [], []
    cfg = ValidationConfig(tau=tau)
    for s in _TEST:
        exts = extractor.extract(s)
        base.append((s, exts, _baseline_decisions(exts)))
        val.append((s, exts, validate_results(exts, s.text, cfg)))
    return base, val


def test_validation_eliminates_false_accepts():
    # 検証層を通すと誤採用(FP)が 0 になる ── これが「絶対に誤った値を入れない」要件。
    _, val = _items(MockExtractor(InjectionConfig()), tau=0.5)
    m = compute_metrics("validated", val)
    assert m.false_positive == 0
    assert m.precision == 1.0


def test_validation_beats_baseline_precision():
    base, val = _items(MockExtractor(InjectionConfig()), tau=0.5)
    bm = compute_metrics("baseline", base)
    vm = compute_metrics("validated", val)
    assert bm.false_positive > 0  # 誤りを注入しているので baseline は誤採用する
    assert vm.precision > bm.precision


def test_grounding_alone_catches_all_injected_errors():
    # τ=0 (確信度しきい値を無効化) でも、接地+帰属だけで全注入誤りを捕捉できる。
    _, val = _items(MockExtractor(InjectionConfig()), tau=0.0)
    m = compute_metrics("tau0", val)
    assert m.false_positive == 0
    assert m.error_catch_rate == 1.0


def test_clean_extractor_no_false_rejects():
    # 誤りなし入力では検証層が正しい値を1件も落とさない (過棄却=0)。
    _, val = _items(MockExtractor(InjectionConfig.clean()), tau=0.5)
    m = compute_metrics("clean", val)
    assert m.false_positive == 0
    assert m.false_reject == 0
    assert m.coverage == 1.0


def test_slot_swap_is_rejected_by_attribution():
    # issuer↔recipient を必ず入替えて、帰属チェックが reject することを確認 (C2)。
    cfg = InjectionConfig(0.0, 0.0, slot_swap=1.0, hallucination=0.0, low_conf=0.0)
    extractor = MockExtractor(cfg)
    found_swap = False
    for s in _TEST:
        exts = extractor.extract(s)
        ds = {d.field_id: d for d in validate_results(exts, s.text, ValidationConfig(0.5))}
        for fid in ("issuer_name", "recipient_name"):
            d = ds[fid]
            found_swap = True
            assert d.decision is Decision.REJECT
            assert "attribution:reject" in d.validator_votes
    assert found_swap
