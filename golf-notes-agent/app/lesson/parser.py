"""レッスン計測テキストの読み取り (§4.2.1)。LLM は使わず、決まった書式どおりに読む。

1 球は ``YYYY/MM/DD HH:MM <クラブ>`` の行から始まり、``項目: 値`` が ``/`` 区切りか 1 行ずつ続く。

    2026/10/07 17:09 7アイアン
    飛距離: 149.9yd / キャリー: 131.4yd / ラン: 18.5yd
    ...
    サイドスピン: 857rpm（ドロー・左回転）/ クラブ軌道: 5.8°（In-Out）/ フェース角度: 右 1.9°（Opened）

符号の規約: 右・オープン・イントゥアウトを正 (右打ち前提)。画面の表記は labels に原文のまま残す。
知らない項目は extra に原文のまま残し、読めなかった行は行番号を返す。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

PARSER_VERSION = "1"

HEADER = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})\s*(.*)$")
# 「/」で項目を区切る。ただし「m/s」の / では切らない (次に「項目名:」が来るときだけ切る)
SPLIT = re.compile(r"\s*/\s*(?=[^\d\s/:]+:)")
ITEM = re.compile(r"^([^:]+?)\s*:\s*(.+)$")
VALUE = re.compile(
    r"^(?P<dir>左|右)?\s*(?P<num>[-+]?\d+(?:\.\d+)?)\s*(?P<unit>yd|m/s|m|°|rpm)?\s*(?:\((?P<note>[^)]*)\))?$"
)


@dataclass(frozen=True)
class Field:
    column: str
    unit: str | None
    # 左右の向きで符号が決まる項目
    directional: bool = False


FIELDS: dict[str, Field] = {
    "飛距離": Field("total_yd", "yd"),
    "キャリー": Field("carry_yd", "yd"),
    "ラン": Field("run_yd", "yd"),
    "クラブスピード": Field("club_speed_mps", "m/s"),
    "ボールスピード": Field("ball_speed_mps", "m/s"),
    "ミート率": Field("smash_factor", None),
    "最高到達点": Field("apex_m", "m"),
    "落下角度": Field("descent_angle_deg", "°"),
    "左右のズレ": Field("offline_yd", "yd", directional=True),
    "打ち上げ角度(縦)": Field("launch_v_deg", "°"),
    "バックスピン": Field("backspin_rpm", "rpm"),
    "打ち出し角度(横)": Field("launch_h_deg", "°", directional=True),
    "サイドスピン": Field("sidespin_rpm", "rpm"),
    "クラブ軌道": Field("club_path_deg", "°"),
    "フェース角度": Field("face_angle_deg", "°", directional=True),
}
COLUMNS = tuple(f.column for f in FIELDS.values())
REQUIRED = ("total_yd", "carry_yd", "club_speed_mps", "ball_speed_mps")

# 表記 → 符号。左右の向き、サイドスピンの回転、クラブ軌道、フェースの向き
SIDE_SIGN = {"左": -1, "右": 1}
SPIN_WORDS = {"左回転": -1, "ドロー": -1, "フック": -1, "右回転": 1, "フェード": 1, "スライス": 1}
PATH_WORDS = {"in-out": 1, "インサイドアウト": 1, "out-in": -1, "アウトサイドイン": -1}
FACE_WORDS = {"opened": 1, "open": 1, "オープン": 1, "closed": -1, "close": -1, "クローズ": -1}

CLUB_WORDS = (
    (re.compile(r"^(?:1w|ドライバー|driver|1ウッド)$"), "1W"),
    (re.compile(r"^(?:(\d+)w|(\d+)ウッド)$"), "{}W"),
    (re.compile(r"^スプーン$"), "3W"),
    (re.compile(r"^クリーク$"), "5W"),
    (re.compile(r"^(?:(\d+)?(?:ut|u|h|ユーティリティ|ハイブリッド))$"), "{}UT"),
    (re.compile(r"^(?:(\d+)i|(\d+)(?:番)?アイアン)$"), "{}I"),
    (re.compile(r"^(?:pw|ピッチング(?:ウェッジ)?)$"), "PW"),
    (re.compile(r"^(?:aw|gw|アプローチ(?:ウェッジ)?|ギャップウェッジ)$"), "AW"),
    (re.compile(r"^(?:sw|サンド(?:ウェッジ)?)$"), "SW"),
    (re.compile(r"^(?:lw|ロブ(?:ウェッジ)?)$"), "LW"),
    (re.compile(r"^(?:pt|パター)$"), "PT"),
)


@dataclass
class Shot:
    shot_no: int
    shot_at: datetime
    club: str | None
    club_label: str
    line_no: int
    values: dict[str, float] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    extra: dict[str, str] = field(default_factory=dict)
    # 読めたが表記と符号が食い違う・向きがない項目 (検算で flag にする)
    direction_issues: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ParseResult:
    shots: list[Shot]
    # 読めなかった行 (1 始まりの行番号, 原文)
    unreadable: list[tuple[int, str]]


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip()


def normalize_club(label: str) -> str | None:
    key = re.sub(r"\s+", "", _norm(label)).lower()
    for pattern, template in CLUB_WORDS:
        m = pattern.match(key)
        if m:
            number = next((g for g in m.groups() if g), "")
            return template.format(number) if "{}" in template else template
    return None


def looks_like_metrics(text: str) -> bool:
    """ボタンを押さずに貼ったときの自動判定。日時とクラブの行と「キャリー:」があれば計測とみなす。"""
    norm = _norm(text)
    return any(HEADER.match(line.strip()) for line in norm.splitlines()) and "キャリー" in norm


def _note_sign(note: str, words: dict[str, int]) -> int | None:
    low = note.lower().replace(" ", "")
    signs = {sign for word, sign in words.items() if word in low}
    return signs.pop() if len(signs) == 1 else None


def _apply(shot: Shot, label: str, raw_value: str) -> bool:
    spec = FIELDS.get(label)
    if spec is None:
        shot.extra[label] = raw_value
        return True
    m = VALUE.match(raw_value)
    if m is None or (m["unit"] and spec.unit and m["unit"] != spec.unit):
        return False
    number = float(m["num"])
    side, note = m["dir"], (m["note"] or "").strip()
    column = spec.column
    if side or note:
        shot.labels[column] = raw_value

    sign: int | None = None
    if spec.directional:
        sign = SIDE_SIGN.get(side or "")
        if column == "face_angle_deg" and note:
            face = _note_sign(note, FACE_WORDS)
            if sign is not None and face is not None and face != sign:
                shot.direction_issues.append(column)
            sign = sign if sign is not None else face
        if sign is None and number != 0:
            shot.direction_issues.append(column)
    elif column == "sidespin_rpm" and number != 0:
        sign = _note_sign(note, SPIN_WORDS)
        if sign is None:
            shot.direction_issues.append(column)
    elif column == "club_path_deg" and note:
        sign = _note_sign(note, PATH_WORDS)
        if sign is None or number < 0 and sign > 0:
            shot.direction_issues.append(column)

    shot.values[column] = abs(number) * sign if sign is not None else number
    return True


def parse(text: str, tz: ZoneInfo) -> ParseResult:
    shots: list[Shot] = []
    unreadable: list[tuple[int, str]] = []
    current: Shot | None = None
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = _norm(raw_line)
        if not line:
            continue
        header = HEADER.match(line)
        if header:
            y, mo, d, h, mi, club_label = header.groups()
            try:
                shot_at = datetime(int(y), int(mo), int(d), int(h), int(mi), tzinfo=tz)
            except ValueError:
                unreadable.append((line_no, raw_line.strip()))
                current = None
                continue
            club_label = club_label.strip()
            current = Shot(
                shot_no=len(shots) + 1,
                shot_at=shot_at,
                club=normalize_club(club_label) if club_label else None,
                club_label=club_label,
                line_no=line_no,
            )
            shots.append(current)
            continue
        if current is None:
            unreadable.append((line_no, raw_line.strip()))
            continue
        ok = False
        for part in SPLIT.split(line):
            item = ITEM.match(part.strip())
            if item and _apply(current, item[1].strip(), item[2].strip()):
                ok = True
            elif part.strip():
                ok = False
                break
        if not ok:
            unreadable.append((line_no, raw_line.strip()))
    return ParseResult(shots=shots, unreadable=unreadable)
