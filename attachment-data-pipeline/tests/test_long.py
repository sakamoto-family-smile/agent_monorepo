"""長文 (実物スケール) 財務資料とチャンク分割のテスト。"""

from __future__ import annotations

from attachment_pipeline.eval.metrics import compute_metrics
from attachment_pipeline.eval.run_financial import run
from attachment_pipeline.extract.financial_mock import (
    FinancialInjectionConfig,
    FinancialMockExtractor,
)
from attachment_pipeline.synth.financial_long import generate_long_dataset, generate_long_sample
from attachment_pipeline.validate.chunking import chunk_text

_TEST = generate_long_dataset(70, 90, target_chars=20000)


def test_long_doc_reaches_target_scale():
    s = generate_long_sample(70, target_chars=20000)
    assert len(s.text) >= 20000


def test_long_doc_spans_intact_under_noise():
    # 撹乱テーブル・定性記述を挟んでも gold span は原文の正しい位置を指す。
    for s in _TEST:
        for fid, (a, b) in s.spans.items():
            assert s.text[a:b] == s.gold_value(fid)


def test_chunking_preserves_global_offsets():
    # 各チャンクの global_start + ローカル find が原文の真の位置に一致する。
    s = generate_long_sample(71, target_chars=20000)
    chunks = chunk_text(s.text)
    assert len(chunks) > 1
    for fid, (a, b) in s.spans.items():
        val = s.gold_value(fid)
        located = False
        for c in chunks:
            if c.global_start <= a and b <= c.global_start + len(c.text):
                local = c.text.find(val)
                while local != -1:
                    if c.to_global(local) == a:
                        located = True
                        break
                    local = c.text.find(val, local + 1)
            if located:
                break
        assert located, f"{fid} のグローバルオフセットを復元できない"


def test_chunk_concatenation_covers_document():
    # チャンクは原文全体をカバーする (オーバーラップ込みで欠落なし)。
    s = generate_long_sample(72, target_chars=20000)
    chunks = chunk_text(s.text)
    # 先頭チャンクは原文先頭から、最終チャンクは原文末尾までを含む。
    assert chunks[0].global_start == 0
    last = chunks[-1]
    assert last.global_start + len(last.text) == len(s.text)


def test_precision_holds_on_long_docs():
    # 長文・数値衝突下でも検証層は誤採用ゼロを維持する。
    _, val = run(_TEST, FinancialMockExtractor(FinancialInjectionConfig()), tau=0.5)
    m = compute_metrics("long", val)
    assert m.false_positive == 0
    assert m.precision == 1.0


def test_clean_long_no_false_rejects():
    # 撹乱の数値衝突があっても、正しい値を誤って棄却しない (evidence_span 絞り込みの有効性)。
    _, val = run(_TEST, FinancialMockExtractor(FinancialInjectionConfig.clean()), tau=0.5)
    m = compute_metrics("clean-long", val)
    assert m.false_positive == 0
    assert m.false_reject == 0
    assert m.coverage == 1.0
