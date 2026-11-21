"""財務資料向けの誤り注入モック抽出器。

財務固有の precision リスクを決定的に再現する:
  - SCALE_DROP : 「1,495,000百万円」を単位忘れで「1,495,000」(=円) と返す
  - SIGN_FLIP  : 「△12,345百万円」(赤字) を「12,345百万円」(黒字) と返す
  - WRONG_PERIOD: 当期の値に前期の値を入れる (列取り違え=財務版C2)
  - SUBSTRING_TRAP / HALLUCINATION / NORMALIZED / LOW_CONF (請求書版と同趣旨)

誤りには高確信度を付与する (LLM は自信を持って間違える)。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import StrEnum

from ..contracts import ExtractionResult
from ..schema import FieldType
from ..schema_financial import period_partner
from ..synth.generator import GoldSample

_EVIDENCE_PAD = 14
_HIGH_CONF = 0.92
_LOW_CONF = 0.30
_FAKE_COMPANY = "架空製作所株式会社"


class ErrorMode(StrEnum):
    CORRECT = "correct"
    NORMALIZED = "normalized"
    SCALE_DROP = "scale_drop"
    SIGN_FLIP = "sign_flip"
    WRONG_PERIOD = "wrong_period"
    SUBSTRING_TRAP = "substring_trap"
    HALLUCINATION = "hallucination"
    LOW_CONF = "low_conf"


@dataclass(frozen=True)
class FinancialInjectionConfig:
    normalized: float = 0.12
    scale_drop: float = 0.12
    sign_flip: float = 0.08
    wrong_period: float = 0.12
    substring_trap: float = 0.06
    hallucination: float = 0.05
    low_conf: float = 0.10

    @staticmethod
    def clean() -> FinancialInjectionConfig:
        return FinancialInjectionConfig(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def _evidence(text: str, start: int, end: int) -> str:
    a = max(0, start - _EVIDENCE_PAD)
    b = min(len(text), end + _EVIDENCE_PAD)
    return text[a:b]


class FinancialMockExtractor:
    def __init__(self, config: FinancialInjectionConfig | None = None, seed_salt: int = 11) -> None:
        self._cfg = config or FinancialInjectionConfig()
        self._salt = seed_salt

    def extract(self, sample: GoldSample) -> list[ExtractionResult]:
        rng = random.Random(sample.sample_id * 2003 + self._salt)
        modes = self._assign_modes(sample, rng)
        return [
            self._build(sample, fid, modes[fid])
            for fid in sample.spans
        ]

    def _assign_modes(self, sample: GoldSample, rng: random.Random) -> dict[str, ErrorMode]:
        modes: dict[str, ErrorMode] = dict.fromkeys(sample.spans, ErrorMode.CORRECT)
        c = self._cfg

        # 期間取り違えはペア単位 (current+prior を揃えて入替)。
        for fid in list(modes):
            if not fid.endswith("_current"):
                continue
            partner = period_partner(fid)
            if partner in modes and rng.random() < c.wrong_period:
                modes[fid] = ErrorMode.WRONG_PERIOD
                modes[partner] = ErrorMode.WRONG_PERIOD

        for fid in modes:
            if modes[fid] is ErrorMode.WRONG_PERIOD:
                continue
            ftype = sample.field_types[fid]
            is_amount = ftype is FieldType.AMOUNT
            r = rng.random()
            cum = c.normalized
            if r < cum and ftype in (FieldType.AMOUNT, FieldType.NUMERIC, FieldType.DATE):
                modes[fid] = ErrorMode.NORMALIZED
                continue
            cum += c.scale_drop
            if r < cum and is_amount:
                modes[fid] = ErrorMode.SCALE_DROP
                continue
            cum += c.sign_flip
            if r < cum and is_amount:
                modes[fid] = ErrorMode.SIGN_FLIP
                continue
            cum += c.substring_trap
            if r < cum and is_amount:
                modes[fid] = ErrorMode.SUBSTRING_TRAP
                continue
            cum += c.hallucination
            if r < cum:
                modes[fid] = ErrorMode.HALLUCINATION
                continue
            cum += c.low_conf
            if r < cum:
                modes[fid] = ErrorMode.LOW_CONF
        return modes

    def _build(self, sample: GoldSample, fid: str, mode: ErrorMode) -> ExtractionResult:
        text = sample.text
        ftype = sample.field_types[fid]
        start, end = sample.spans[fid]
        gold = text[start:end]
        ev = _evidence(text, start, end)

        if mode is ErrorMode.CORRECT:
            return self._mk(fid, ftype, gold, ev, _HIGH_CONF)
        if mode is ErrorMode.LOW_CONF:
            return self._mk(fid, ftype, gold, ev, _LOW_CONF)
        if mode is ErrorMode.NORMALIZED:
            return self._mk(fid, ftype, self._normalized(gold, ftype), ev, _HIGH_CONF)
        if mode is ErrorMode.SCALE_DROP:
            return self._mk(fid, ftype, gold.replace("百万円", ""), ev, _HIGH_CONF)
        if mode is ErrorMode.SIGN_FLIP:
            flipped = gold[1:] if gold[:1] in "△▲" else "△" + gold
            return self._mk(fid, ftype, flipped, ev, _HIGH_CONF)
        if mode is ErrorMode.SUBSTRING_TRAP:
            # 先頭カンマ区切りを落として桁を削る (1,495,000百万円 → 495,000百万円)
            digits = gold
            if "," in digits:
                trap = digits.split(",", 1)[1]
                return self._mk(fid, ftype, trap, ev, _HIGH_CONF)
            return self._mk(fid, ftype, gold[1:] or gold, ev, _HIGH_CONF)
        if mode is ErrorMode.WRONG_PERIOD:
            partner = period_partner(fid)
            ps, pe = sample.spans[partner]
            return self._mk(fid, ftype, text[ps:pe], _evidence(text, ps, pe), _HIGH_CONF)
        # HALLUCINATION
        return self._mk(fid, ftype, self._fake(ftype), ev, _HIGH_CONF)

    @staticmethod
    def _normalized(gold: str, ftype: FieldType) -> str:
        if ftype is FieldType.AMOUNT:
            return gold.replace(",", "")  # 単位は保持 (正しい値のまま)
        if ftype is FieldType.DATE:
            return _jp_to_iso(gold)  # 原文(和暦表記)を ISO に正規化して返す
        return gold

    @staticmethod
    def _fake(ftype: FieldType) -> str:
        if ftype is FieldType.AMOUNT:
            return "99,999,999百万円"
        if ftype is FieldType.NUMERIC:
            return "999.99"
        if ftype is FieldType.DATE:
            return "1999年12月31日"
        if ftype is FieldType.CODE:
            return "E00000"
        return _FAKE_COMPANY

    @staticmethod
    def _mk(fid, ftype, value, ev, conf) -> ExtractionResult:
        return ExtractionResult(
            field_id=fid,
            field_type=ftype,
            value=value,
            evidence_span=ev,
            chunk_id=0,
            global_start=0,
            extract_conf=conf,
        )


def _jp_to_iso(s: str) -> str:
    import re

    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", s)
    if not m:
        return s
    y, mo, d = (int(g) for g in m.groups())
    return f"{y:04d}-{mo:02d}-{d:02d}"
