"""合成-but-grounded データ生成。"""

from __future__ import annotations

from .generator import GoldSample, LabelOccurrence, generate_dataset, generate_sample

__all__ = ["GoldSample", "LabelOccurrence", "generate_sample", "generate_dataset"]
