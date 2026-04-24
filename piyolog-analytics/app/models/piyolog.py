"""ピヨログドメインモデル (不変 dataclass + enum)。

パース結果と永続化レコードを分離:
  - `ParsedEvent`: パーサが 1 行から生成する中間表現 (timezone-aware datetime)
  - `StoredEvent`: SQLite に INSERT される形 (ISO8601 文字列化済み)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class EventType(StrEnum):
    """正規化済みイベント種別。

    ぴよログ UI の表記ゆれは `EVENT_TYPE_ALIASES` (parser.piyolog_parser) で吸収する。
    """

    FORMULA = "formula"                    # ミルク
    EXPRESSED_MILK = "expressed_milk"      # 搾母乳
    BREAST_MILK = "breast_milk"            # 母乳
    SLEEP = "sleep"                        # 寝る
    WAKE = "wake"                          # 起きる
    PEE = "pee"                            # おしっこ
    POO = "poo"                            # うんち
    TEMPERATURE = "temperature"            # 体温
    WEIGHT = "weight"                      # 体重
    HEIGHT = "height"                      # 身長
    HEAD_CIRCUMFERENCE = "head_circumference"  # 頭囲
    BATH = "bath"                          # お風呂
    MEDICINE = "medicine"                  # お薬 / 服薬
    BABY_FOOD = "baby_food"                # 離乳食
    MEMO = "memo"                          # コメント・メモ
    OTHER = "other"                        # フォールバック (パース不能)


@dataclass(frozen=True)
class ParsedEvent:
    """パーサが 1 行から生成する中間表現。"""

    timestamp: datetime                    # timezone-aware (JST)
    event_type: EventType
    raw_text: str                          # 原文 1 行 (冪等 key 生成用)
    volume_ml: float | None = None
    left_minutes: int | None = None
    right_minutes: int | None = None
    sleep_minutes: int | None = None       # WAKE のみ: 直前睡眠時間
    temperature_c: float | None = None
    weight_kg: float | None = None
    height_cm: float | None = None
    head_circumference_cm: float | None = None
    memo: str | None = None                # MEMO / POO の性状 / OTHER の raw 保持


@dataclass(frozen=True)
class ParsedDay:
    """1 日分のパース結果。monthly export なら複数束ねて返す。"""

    date: datetime                         # 00:00 JST
    baby_name: str | None
    age_years: int | None
    age_months: int | None
    age_days: int | None
    events: list[ParsedEvent] = field(default_factory=list)
    comment: str | None = None


@dataclass(frozen=True)
class ParseResult:
    """ファイル 1 本のパース結果。"""

    days: list[ParsedDay]
    total_events: int
    baby_name: str | None                  # 代表名 (最初に出現したもの)


@dataclass(frozen=True)
class StoredEvent:
    """SQLite 永続化レコード。"""

    event_id: str
    family_id: str
    source_user_id: str
    child_id: str
    event_timestamp: str                   # ISO8601 (+09:00)
    event_date: str                        # YYYY-MM-DD (JST)
    event_type: str
    volume_ml: float | None
    left_minutes: int | None
    right_minutes: int | None
    sleep_minutes: int | None
    temperature_c: float | None
    weight_kg: float | None
    height_cm: float | None
    head_circumference_cm: float | None
    memo: str | None
    raw_text: str
    import_batch_id: str
    imported_at: str                       # ISO8601


@dataclass(frozen=True)
class ImportBatch:
    """取り込み単位の履歴。"""

    batch_id: str
    family_id: str
    source_user_id: str
    source_filename: str | None
    raw_text_hash: str
    event_count: int
    imported_at: str
    rolled_back_at: str | None = None
