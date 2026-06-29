"""誤り注入モック抽出器。

実 LLM 抽出器が犯す典型的な誤りを **決定的に再現** し、検証層がそれらを弾けるか
を測る。重要な設計上の点: 誤り (trap/slot/halluc) には **高い確信度** を付与する
── LLM は「自信を持って間違える」(設計ガイド 3.2) ため、確信度だけでは捕捉できず
接地・帰属・再検証で捕まえる必要があることを示す。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import StrEnum

from ..contracts import ExtractionResult
from ..schema import MUTUALLY_EXCLUSIVE_SLOTS, field_type_of
from ..synth.generator import GoldSample

_EVIDENCE_PAD = 12
_HIGH_CONF = 0.92
_LOW_CONF = 0.30
_FAKE_NAMES = ["株式会社架空ホールディングス", "幻影トレーディング株式会社"]


class ErrorMode(StrEnum):
    """注入する誤りモード。"""

    CORRECT = "correct"  # 原文表記そのまま (採用されるべき)
    NORMALIZED = "normalized"  # 正規化済みだが正しい値 (H1: 採用されるべき)
    SUBSTRING_TRAP = "substring_trap"  # 18800→800 (接地で reject されるべき)
    SLOT_SWAP = "slot_swap"  # issuer↔recipient 入替 (帰属で reject されるべき)
    HALLUCINATION = "hallucination"  # 原文に無い値 (接地で reject されるべき)
    LOW_CONF = "low_conf"  # 正しいが低確信 (abstain されるべき)


@dataclass(frozen=True)
class InjectionConfig:
    """誤り注入の確率。合計が1未満なら残りは CORRECT。"""

    normalized: float = 0.15
    substring_trap: float = 0.10
    slot_swap: float = 0.08
    hallucination: float = 0.07
    low_conf: float = 0.10

    @staticmethod
    def clean() -> InjectionConfig:
        """誤りなし (ベースライン用: すべて CORRECT)。"""
        return InjectionConfig(0.0, 0.0, 0.0, 0.0, 0.0)


def _evidence(text: str, start: int, end: int) -> str:
    a = max(0, start - _EVIDENCE_PAD)
    b = min(len(text), end + _EVIDENCE_PAD)
    return text[a:b]


def _normalize_value(field_type_name: str, gold_text: str, iso: str | None) -> str:
    if field_type_name in {"amount", "numeric"}:
        return gold_text.replace(",", "")
    if field_type_name == "date" and iso is not None:
        return iso
    return gold_text


class MockExtractor:
    """GoldSample から ExtractionResult[] を誤り注入付きで生成する。"""

    def __init__(self, config: InjectionConfig | None = None, seed_salt: int = 7) -> None:
        self._cfg = config or InjectionConfig()
        self._salt = seed_salt

    def extract(self, sample: GoldSample) -> list[ExtractionResult]:
        rng = random.Random(sample.sample_id * 1009 + self._salt)
        modes = self._assign_modes(sample, rng)
        results: list[ExtractionResult] = []
        for field_id, (start, end) in sample.spans.items():
            mode = modes[field_id]
            results.append(self._build(sample, field_id, start, end, mode))
        return results

    # ── モード割当 ───────────────────────────────────────────────
    def _assign_modes(self, sample: GoldSample, rng: random.Random) -> dict[str, ErrorMode]:
        modes: dict[str, ErrorMode] = dict.fromkeys(sample.spans, ErrorMode.CORRECT)
        c = self._cfg

        # スロット入替はペア単位で適用 (両フィールドが揃って存在する場合のみ)。
        for a, b in MUTUALLY_EXCLUSIVE_SLOTS:
            if a in modes and b in modes and rng.random() < c.slot_swap:
                modes[a] = ErrorMode.SLOT_SWAP
                modes[b] = ErrorMode.SLOT_SWAP

        for field_id in modes:
            if modes[field_id] is ErrorMode.SLOT_SWAP:
                continue
            r = rng.random()
            ftype = field_type_of(field_id).value
            cum = 0.0
            cum += c.normalized
            if r < cum and ftype in {"amount", "numeric", "date"}:
                modes[field_id] = ErrorMode.NORMALIZED
                continue
            cum += c.substring_trap
            if r < cum and ftype in {"amount", "numeric"}:
                modes[field_id] = ErrorMode.SUBSTRING_TRAP
                continue
            cum += c.hallucination
            if r < cum:
                modes[field_id] = ErrorMode.HALLUCINATION
                continue
            cum += c.low_conf
            if r < cum:
                modes[field_id] = ErrorMode.LOW_CONF
        return modes

    # ── 1 フィールドの ExtractionResult 生成 ─────────────────────
    def _build(
        self, sample: GoldSample, field_id: str, start: int, end: int, mode: ErrorMode
    ) -> ExtractionResult:
        text = sample.text
        ftype = field_type_of(field_id)
        gold_text = text[start:end]
        iso = self._iso_for(sample, field_id)

        if mode is ErrorMode.CORRECT:
            return self._mk(field_id, ftype, gold_text, _evidence(text, start, end), _HIGH_CONF)

        if mode is ErrorMode.LOW_CONF:
            return self._mk(field_id, ftype, gold_text, _evidence(text, start, end), _LOW_CONF)

        if mode is ErrorMode.NORMALIZED:
            val = _normalize_value(ftype.value, gold_text, iso)
            return self._mk(field_id, ftype, val, _evidence(text, start, end), _HIGH_CONF)

        if mode is ErrorMode.SUBSTRING_TRAP:
            # gold にカンマがあれば末尾セグメントを取り出す (18,800→800)。
            if "," in gold_text:
                val = gold_text.split(",")[-1]
            else:
                val = gold_text[1:] if len(gold_text) > 1 else gold_text
            return self._mk(field_id, ftype, val, _evidence(text, start, end), _HIGH_CONF)

        if mode is ErrorMode.SLOT_SWAP:
            other = self._swap_partner(field_id)
            os, oe = sample.spans[other]
            other_val = text[os:oe]
            # 値は相手のもの。evidence も相手の領域を指す (誤接地の構造を再現)。
            return self._mk(field_id, ftype, other_val, _evidence(text, os, oe), _HIGH_CONF)

        # HALLUCINATION
        fake = self._fake_value(ftype.value)
        return self._mk(field_id, ftype, fake, _evidence(text, start, end), _HIGH_CONF)

    @staticmethod
    def _swap_partner(field_id: str) -> str:
        for a, b in MUTUALLY_EXCLUSIVE_SLOTS:
            if field_id == a:
                return b
            if field_id == b:
                return a
        return field_id

    @staticmethod
    def _iso_for(sample: GoldSample, field_id: str) -> str | None:
        if field_id == "issue_date":
            return sample.record.issue_date
        if field_id == "due_date":
            return sample.record.due_date
        return None

    @staticmethod
    def _fake_value(ftype: str) -> str:
        if ftype in {"amount", "numeric"}:
            return "99999999"
        if ftype == "date":
            return "1999年12月31日"
        if ftype == "code":
            return "INV-0000-00000"
        return _FAKE_NAMES[0]

    @staticmethod
    def _mk(field_id, ftype, value, evidence, conf) -> ExtractionResult:
        return ExtractionResult(
            field_id=field_id,
            field_type=ftype,
            value=value,
            evidence_span=evidence,
            chunk_id=0,
            global_start=0,
            extract_conf=conf,
        )
