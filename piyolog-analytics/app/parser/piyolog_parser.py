"""ぴよログ .txt のパーサ。

設計方針:
  - pure Python、pandas / numpy に依存しない
  - 状態機械 (`_State`) で daily / monthly 両フォーマットを同じコードで扱う
  - 未知イベントは `EventType.OTHER` で raw_text を memo にフォールバック
    (情報ロスを防ぐ)
  - 合計行 (`ミルク合計`, `睡眠合計` 等) は冗長なのでスキップ
  - 参考 (MIT license):
    * shu65/piyolog_reader — state machine 設計
    * konnyaku256/piyolog-analytics — regex 切り出し
    どちらもコード自体は流用せず、パターンだけ参考にした pure Python 実装。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from enum import Enum, auto

from models.piyolog import EventType, ParsedDay, ParsedEvent, ParseResult

JST = timezone(timedelta(hours=9), "Asia/Tokyo")

# ---------------------------------------------------------------------------
# 状態機械
# ---------------------------------------------------------------------------


class _State(Enum):
    START = auto()
    DATE = auto()
    NAME_AGE = auto()
    BLANK_AFTER_NAME = auto()
    EVENTS = auto()
    TOTALS = auto()
    COMMENT = auto()


# ---------------------------------------------------------------------------
# 正規表現
# ---------------------------------------------------------------------------

_HEADER_RE = re.compile(r"^【ぴよログ】(\d{4}/\d{1,2}(?:/\d{1,2}(?:\([^)]+\))?)?)\s*$")
_DATE_LINE_RE = re.compile(r"^(\d{4}/\d{1,2}/\d{1,2})\([^)]+\)\s*$")
_NAME_AGE_RE = re.compile(
    r"^(\S+)\s*\(\s*(\d+)歳(\d+)か月(?:(\d+)日)?\s*\)\s*$"
)
_EVENT_RE = re.compile(r"^(\d{1,2}):(\d{2})\s{1,}(.+)$")
_SEPARATOR_RE = re.compile(r"^-{5,}\s*$")

# 合計行判定 (スキップ対象)
_TOTAL_LINE_TOKENS = (
    "母乳合計",
    "ミルク合計",
    "搾母乳合計",
    "離乳食合計",
    "睡眠合計",
    "おしっこ合計",
    "うんち合計",
    "お風呂合計",
)

# 値抽出
_ML_RE = re.compile(r"(\d+(?:\.\d+)?)ml")
_CM_RE = re.compile(r"(\d+(?:\.\d+)?)cm")
_KG_RE = re.compile(r"(\d+(?:\.\d+)?)kg")
_CELSIUS_RE = re.compile(r"(\d+(?:\.\d+)?)°?C")
_LEFT_RE = re.compile(r"左(\d+)分")
_RIGHT_RE = re.compile(r"右(\d+)分")
_WAKE_DURATION_RE = re.compile(r"(\d+)時間(\d+)分")

# イベント名 → EventType マッピング (先頭一致で判定)
_EVENT_NAME_ALIASES: list[tuple[str, EventType]] = [
    ("搾母乳", EventType.EXPRESSED_MILK),
    ("ミルク", EventType.FORMULA),
    ("母乳", EventType.BREAST_MILK),
    ("寝る", EventType.SLEEP),
    ("起きる", EventType.WAKE),
    ("おしっこ", EventType.PEE),
    ("うんち", EventType.POO),
    ("体温", EventType.TEMPERATURE),
    ("体重", EventType.WEIGHT),
    ("身長", EventType.HEIGHT),
    ("頭囲", EventType.HEAD_CIRCUMFERENCE),
    ("お風呂", EventType.BATH),
    ("お薬", EventType.MEDICINE),
    ("服薬", EventType.MEDICINE),
    ("離乳食", EventType.BABY_FOOD),
]


# ---------------------------------------------------------------------------
# 公開 API
# ---------------------------------------------------------------------------


def parse_piyolog_text(text: str) -> ParseResult:
    """ぴよログの .txt 文字列をパースする。

    daily / monthly どちらのフォーマットも同じ処理で扱う:
      daily   : 先頭 `【ぴよログ】YYYY/MM/DD(曜)` で日付確定、以降 1 日分
      monthly : 先頭 `【ぴよログ】YYYY/MM`、`----------` 区切りで複数日分
    """
    lines = text.splitlines()
    days: list[ParsedDay] = []
    baby_name_first: str | None = None

    state = _State.START
    current_date: datetime | None = None
    current_name: str | None = None
    current_age: tuple[int, int, int | None] | None = None
    current_events: list[ParsedEvent] = []
    current_comment_lines: list[str] = []

    def flush_day() -> None:
        nonlocal current_events, current_comment_lines
        if current_date is None:
            return
        days.append(
            ParsedDay(
                date=current_date,
                baby_name=current_name,
                age_years=current_age[0] if current_age else None,
                age_months=current_age[1] if current_age else None,
                age_days=current_age[2] if current_age else None,
                events=list(current_events),
                comment="\n".join(current_comment_lines).strip() or None,
            )
        )
        current_events = []
        current_comment_lines = []

    for raw_line in lines:
        line = raw_line.rstrip()

        # ヘッダ (どの state でも検出する: daily は最初、monthly は開始時のみ)
        header_match = _HEADER_RE.match(line)
        if header_match:
            header_val = header_match.group(1)
            # YYYY/MM/DD(曜) 形式なら daily として即 date 確定
            if re.match(r"^\d{4}/\d{1,2}/\d{1,2}", header_val):
                flush_day()
                try:
                    current_date = datetime.strptime(header_val[:10], "%Y/%m/%d").replace(
                        tzinfo=JST
                    )
                except ValueError:
                    current_date = None
                state = _State.NAME_AGE
            else:
                # YYYY/MM 形式 (monthly) は日付未確定で次の "----------" を待つ
                current_date = None
                state = _State.START
            continue

        # 区切り線: monthly の日付ブロック境界
        if _SEPARATOR_RE.match(line):
            flush_day()
            current_name = None
            current_age = None
            state = _State.DATE
            continue

        # 日付行 (monthly: "YYYY/MM/DD(曜)")
        if state == _State.DATE:
            m = _DATE_LINE_RE.match(line)
            if m:
                try:
                    current_date = datetime.strptime(m.group(1), "%Y/%m/%d").replace(
                        tzinfo=JST
                    )
                except ValueError:
                    current_date = None
                state = _State.NAME_AGE
                continue
            # 空行は読み飛ばす
            if not line.strip():
                continue
            # 日付が出ないまま別物が来たら EVENTS 扱いに戻す
            state = _State.EVENTS

        # 名前 + 年齢行
        if state == _State.NAME_AGE:
            if not line.strip():
                # 空行: EVENTS へ遷移
                state = _State.EVENTS
                continue
            m = _NAME_AGE_RE.match(line)
            if m:
                current_name = m.group(1)
                if baby_name_first is None:
                    baby_name_first = current_name
                age_years = int(m.group(2))
                age_months = int(m.group(3))
                age_days = int(m.group(4)) if m.group(4) else None
                current_age = (age_years, age_months, age_days)
                state = _State.BLANK_AFTER_NAME
                continue
            # マッチしないなら EVENTS 遷移
            state = _State.EVENTS

        if state == _State.BLANK_AFTER_NAME:
            if not line.strip():
                state = _State.EVENTS
                continue
            # 空行なしで即イベント開始の場合もある
            state = _State.EVENTS

        # TOTALS / COMMENT への遷移: 空行 + 合計行系
        if state == _State.EVENTS:
            stripped = line.strip()
            if not stripped:
                state = _State.TOTALS
                continue
            if _is_total_line(stripped):
                state = _State.TOTALS
                continue
            # イベント 1 行をパース
            parsed = _parse_event_line(stripped, current_date)
            if parsed is not None:
                current_events.append(parsed)
            continue

        if state == _State.TOTALS:
            stripped = line.strip()
            if not stripped:
                state = _State.COMMENT
                continue
            if _is_total_line(stripped):
                continue
            # 合計セクションが終わってコメント開始
            current_comment_lines.append(stripped)
            state = _State.COMMENT
            continue

        if state == _State.COMMENT:
            # monthly 区切り "----------" は上の _SEPARATOR_RE で既に処理済み
            stripped = line.strip()
            if stripped:
                current_comment_lines.append(stripped)
            continue

    flush_day()
    total = sum(len(d.events) for d in days)
    return ParseResult(days=days, total_events=total, baby_name=baby_name_first)


# ---------------------------------------------------------------------------
# 内部ヘルパ
# ---------------------------------------------------------------------------


def _is_total_line(line: str) -> bool:
    return any(line.startswith(tok) for tok in _TOTAL_LINE_TOKENS)


def _parse_event_line(line: str, current_date: datetime | None) -> ParsedEvent | None:
    """イベント 1 行をパース。date が未確定 or 行がイベント形式でないなら None。"""
    if current_date is None:
        return None
    m = _EVENT_RE.match(line)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2))
    body = m.group(3).strip()
    timestamp = current_date.replace(hour=hour, minute=minute, second=0, microsecond=0)

    event_type = _classify_event(body)
    value_str = _strip_event_name(body, event_type)

    return _build_event(
        event_type=event_type,
        timestamp=timestamp,
        value_str=value_str,
        raw_text=line,
    )


def _classify_event(body: str) -> EventType:
    for prefix, et in _EVENT_NAME_ALIASES:
        if body.startswith(prefix):
            return et
    return EventType.OTHER


def _strip_event_name(body: str, event_type: EventType) -> str:
    for prefix, et in _EVENT_NAME_ALIASES:
        if et == event_type and body.startswith(prefix):
            return body[len(prefix):].strip()
    return body


def _build_event(
    *,
    event_type: EventType,
    timestamp: datetime,
    value_str: str,
    raw_text: str,
) -> ParsedEvent:
    kwargs: dict[str, object] = {
        "timestamp": timestamp,
        "event_type": event_type,
        "raw_text": raw_text,
    }

    if event_type == EventType.FORMULA or event_type == EventType.EXPRESSED_MILK:
        m = _ML_RE.search(value_str)
        if m:
            kwargs["volume_ml"] = float(m.group(1))
        else:
            # 「(完食)」等、数値がないケースは memo に保存
            kwargs["memo"] = value_str or None

    elif event_type == EventType.BREAST_MILK:
        left = _LEFT_RE.search(value_str)
        right = _RIGHT_RE.search(value_str)
        if left:
            kwargs["left_minutes"] = int(left.group(1))
        if right:
            kwargs["right_minutes"] = int(right.group(1))
        # ml 指定 (瓶詰め搾母乳扱い) も拾う
        ml = _ML_RE.search(value_str)
        if ml:
            kwargs["volume_ml"] = float(ml.group(1))

    elif event_type == EventType.WAKE:
        m = _WAKE_DURATION_RE.search(value_str)
        if m:
            hours = int(m.group(1))
            minutes = int(m.group(2))
            kwargs["sleep_minutes"] = hours * 60 + minutes

    elif event_type == EventType.TEMPERATURE:
        m = _CELSIUS_RE.search(value_str)
        if m:
            kwargs["temperature_c"] = float(m.group(1))

    elif event_type == EventType.WEIGHT:
        m = _KG_RE.search(value_str)
        if m:
            kwargs["weight_kg"] = float(m.group(1))

    elif event_type == EventType.HEIGHT:
        m = _CM_RE.search(value_str)
        if m:
            kwargs["height_cm"] = float(m.group(1))

    elif event_type == EventType.HEAD_CIRCUMFERENCE:
        m = _CM_RE.search(value_str)
        if m:
            kwargs["head_circumference_cm"] = float(m.group(1))

    elif event_type == EventType.POO:
        # 性状を memo に格納 ("ふつう" / "下痢" / ...)
        if value_str:
            kwargs["memo"] = value_str.strip("()").strip() or None

    elif event_type == EventType.OTHER:
        # 未知イベント: raw 全体を memo に保存
        kwargs["memo"] = raw_text

    elif event_type in (EventType.SLEEP, EventType.PEE, EventType.BATH, EventType.MEDICINE, EventType.BABY_FOOD):
        # 付帯情報があれば memo に保存
        if value_str:
            kwargs["memo"] = value_str

    return ParsedEvent(**kwargs)  # type: ignore[arg-type]
