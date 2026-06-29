"""合成生成器の健全性テスト。"""

from __future__ import annotations

from attachment_pipeline.schema import Invoice
from attachment_pipeline.synth.generator import generate_dataset, generate_sample


def test_spans_point_to_recorded_values():
    # Arrange / Act
    s = generate_sample(42)

    # Assert: 記録された span が原文の正しい位置を指す。
    for field_id, (start, end) in s.spans.items():
        assert 0 <= start < end <= len(s.text)
        assert s.text[start:end] == s.gold_value(field_id)


def test_record_is_schema_valid_and_arithmetic_consistent():
    s = generate_sample(7)
    # Invoice の validator が subtotal+tax==total, qty*unit==amount を強制している。
    assert isinstance(s.record, Invoice)
    assert s.record.subtotal + s.record.tax == s.record.total


def test_deterministic_by_seed():
    a = generate_sample(13)
    b = generate_sample(13)
    assert a.text == b.text
    assert a.record == b.record


def test_dataset_range():
    ds = generate_dataset(0, 5)
    assert [s.sample_id for s in ds] == [0, 1, 2, 3, 4]
