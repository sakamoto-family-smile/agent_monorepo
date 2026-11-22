"""取り込み時の検算 (§4.2.1)。どれかに当てはまる球は確定前に人が見る。"""
from __future__ import annotations

from dataclasses import dataclass

from app.lesson.parser import REQUIRED, Shot

DISTANCE_TOLERANCE_YD = 0.2
SMASH_TOLERANCE = 0.02
# ほぼ真っすぐの球は曲がりの向きの符号が揺れるので判定しない
CURVE_MIN_FACE_TO_PATH_DEG = 1.0
CURVE_MIN_SIDESPIN_RPM = 200

# クラブの種類ごとの妥当な範囲 (外れたら読み違い・入力違いを疑う)
GROUPS = {
    "driver": {"launch_v_deg": (3, 25), "carry_yd": (50, 360), "backspin_rpm": (800, 6000)},
    "wood": {"launch_v_deg": (3, 30), "carry_yd": (50, 320), "backspin_rpm": (1000, 8000)},
    "iron": {"launch_v_deg": (5, 35), "carry_yd": (20, 260), "backspin_rpm": (1500, 11000)},
    "wedge": {"launch_v_deg": (10, 50), "carry_yd": (5, 160), "backspin_rpm": (2000, 13000)},
}
COMMON = {"club_speed_mps": (10, 65), "ball_speed_mps": (5, 95), "smash_factor": (0.5, 1.6)}

MESSAGES = {
    "missing": "必須の項目（飛距離・キャリー・クラブスピード・ボールスピード）が欠けています",
    "distance": "飛距離がキャリー + ランと合いません",
    "smash": "ミート率がボールスピード ÷ クラブスピードと合いません",
    "curve": "サイドスピンの向きとフェースと軌道の差の向きが合いません",
    "direction": "左右・In-Out・Opened などの表記と数値が合いません（または向きがありません）",
    "range": "値がクラブの妥当な範囲を外れています",
    "club": "クラブ名を読み取れません",
}


@dataclass(frozen=True)
class Flag:
    code: str
    detail: str

    @property
    def message(self) -> str:
        return f"{MESSAGES[self.code]}（{self.detail}）" if self.detail else MESSAGES[self.code]


def group(club: str | None) -> str | None:
    if club is None:
        return None
    if club in ("PW", "AW", "SW", "LW"):
        return "wedge"
    if club == "1W":
        return "driver"
    if club.endswith(("W", "UT")):
        return "wood"
    if club.endswith("I"):
        return "iron"
    return None


def check(shot: Shot) -> list[Flag]:
    v = shot.values
    flags: list[Flag] = []
    missing = [c for c in REQUIRED if c not in v]
    if missing:
        flags.append(Flag("missing", ", ".join(missing)))
    if shot.club is None:
        flags.append(Flag("club", shot.club_label or "なし"))
    if {"total_yd", "carry_yd", "run_yd"} <= v.keys():
        diff = v["total_yd"] - (v["carry_yd"] + v["run_yd"])
        if abs(diff) > DISTANCE_TOLERANCE_YD:
            flags.append(Flag("distance", f"差 {diff:+.1f}yd"))
    if {"smash_factor", "ball_speed_mps", "club_speed_mps"} <= v.keys() and v["club_speed_mps"] > 0:
        ratio = v["ball_speed_mps"] / v["club_speed_mps"]
        if abs(ratio - v["smash_factor"]) > SMASH_TOLERANCE:
            flags.append(Flag("smash", f"{ratio:.2f} と {v['smash_factor']:.2f}"))
    if {"face_angle_deg", "club_path_deg", "sidespin_rpm"} <= v.keys():
        ftp = v["face_angle_deg"] - v["club_path_deg"]
        spin = v["sidespin_rpm"]
        if (
            abs(ftp) >= CURVE_MIN_FACE_TO_PATH_DEG
            and abs(spin) >= CURVE_MIN_SIDESPIN_RPM
            and (ftp > 0) != (spin > 0)
        ):
            flags.append(Flag("curve", f"サイドスピン {spin:+.0f}rpm / フェース−軌道 {ftp:+.1f}°"))
    if shot.direction_issues:
        flags.append(Flag("direction", ", ".join(sorted(set(shot.direction_issues)))))
    ranges = {**COMMON, **GROUPS.get(group(shot.club) or "", {})}
    out = [f"{c}={v[c]:g}" for c, (lo, hi) in ranges.items() if c in v and not lo <= v[c] <= hi]
    if out:
        flags.append(Flag("range", ", ".join(out)))
    return flags
