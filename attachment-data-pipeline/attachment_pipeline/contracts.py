"""抽出パイプラインと検証パイプラインを繋ぐ唯一のデータ契約。

設計ガイド 4.7.2 の ``ExtractionResult`` / ``DecidedField`` に対応。
抽出側は「原文文字列のままの値 + 接地に必要な情報」だけを出し、採否は判断しない。
検証側がすべての関門と最終採否を担う。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .schema import FieldType


class Decision(StrEnum):
    """検証層の最終判定。"""

    ACCEPT = "accept"
    REJECT = "reject"  # 関門で誤りと判定 → null
    ABSTAIN = "abstain"  # 確信度不足 → null (ReCoVERR で復活余地)


@dataclass(frozen=True)
class ExtractionResult:
    """抽出器の出力単位 (1 フィールド)。

    value は **原文文字列のまま** (オフセット・正規化は検証側が行う)。
    """

    field_id: str
    field_type: FieldType
    value: str
    evidence_span: str  # value を含む前後の原文一節 (誤接地の抑止に使う)
    chunk_id: int
    global_start: int  # チャンクの原文内開始位置
    extract_conf: float  # 抽出側の自己申告確信度 [0,1]


@dataclass(frozen=True)
class CharInterval:
    """原文全体に対するグローバル文字オフセット。"""

    start: int
    end: int


@dataclass
class DecidedField:
    """検証層の出力単位。value=None は棄却/abstain。"""

    field_id: str
    value: str | None
    char_interval: CharInterval | None
    final_conf: float
    decision: Decision
    validator_votes: list[str] = field(default_factory=list)

    @property
    def is_accepted(self) -> bool:
        return self.decision is Decision.ACCEPT and self.value is not None
