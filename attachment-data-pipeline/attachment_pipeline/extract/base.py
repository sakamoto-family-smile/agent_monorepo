"""抽出器の抽象 (Protocol)。Mock / 実LLM を同じ契約で差し替える。"""

from __future__ import annotations

from typing import Protocol

from ..contracts import ExtractionResult
from ..synth.generator import GoldSample


class Extractor(Protocol):
    """原文 (GoldSample.text) からフィールド値を抽出する。

    実装は ExtractionResult[] を返すだけで採否は判断しない (設計ガイド 4.7)。
    評価では gold span が必要なため GoldSample を受け取るが、実LLM抽出器は
    text しか使わない (gold は無視) ようにできる。
    """

    def extract(self, sample: GoldSample) -> list[ExtractionResult]: ...
