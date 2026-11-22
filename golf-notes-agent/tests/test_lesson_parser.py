"""計測テキストの読み取りと検算 (§4.2.1)。サンプル (2026-11-21 受領) を固定入力にする。"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.lesson.checks import check, group
from app.lesson.parser import looks_like_metrics, normalize_club, parse

JST = ZoneInfo("Asia/Tokyo")
SAMPLE = """2026/10/07 17:09 7アイアン
飛距離: 149.9yd / キャリー: 131.4yd / ラン: 18.5yd
クラブスピード: 31.6m/s / ボールスピード: 44.3m/s / ミート率: 1.40（高い）
最高到達点: 15.7m / 落下角度: 33.1° / 左右のズレ: 左 6.5yd
打ち上げ角度(縦): 16.1° / バックスピン: 4449rpm（少ない）/ 打ち出し角度(横): 右 2.3°
サイドスピン: 857rpm（ドロー・左回転）/ クラブ軌道: 5.8°（In-Out）/ フェース角度: 右 1.9°（Opened）"""

EXPECTED = {
    "total_yd": 149.9,
    "carry_yd": 131.4,
    "run_yd": 18.5,
    "club_speed_mps": 31.6,
    "ball_speed_mps": 44.3,
    "smash_factor": 1.40,
    "apex_m": 15.7,
    "descent_angle_deg": 33.1,
    "offline_yd": -6.5,
    "launch_v_deg": 16.1,
    "backspin_rpm": 4449,
    "launch_h_deg": 2.3,
    "sidespin_rpm": -857,
    "club_path_deg": 5.8,
    "face_angle_deg": 1.9,
}


def one(text: str):
    result = parse(text, JST)
    assert len(result.shots) == 1, result
    return result.shots[0], result


def test_golden_sample():
    shot, result = one(SAMPLE)
    assert result.unreadable == []
    assert shot.shot_at == datetime(2026, 10, 7, 17, 9, tzinfo=JST)
    assert shot.club == "7I" and shot.club_label == "7アイアン"
    assert shot.values == pytest.approx(EXPECTED)
    assert shot.labels == {
        "smash_factor": "1.40(高い)",
        "offline_yd": "左 6.5yd",
        "backspin_rpm": "4449rpm(少ない)",
        "launch_h_deg": "右 2.3°",
        "sidespin_rpm": "857rpm(ドロー・左回転)",
        "club_path_deg": "5.8°(In-Out)",
        "face_angle_deg": "右 1.9°(Opened)",
    }
    assert shot.extra == {} and shot.direction_issues == []
    assert check(shot) == []


def test_one_item_per_line_and_shuffled_order():
    lines = SAMPLE.splitlines()
    items = [p.strip() for line in lines[1:] for p in line.replace("（少ない）/", "（少ない） /").split(" / ")]
    text = "\n".join([lines[0], *reversed(items)])
    shot, result = one(text)
    assert result.unreadable == [] and shot.values == pytest.approx(EXPECTED)


def test_multiple_shots_and_unknown_items():
    second = SAMPLE.replace("17:09 7アイアン", "17:11 ピッチングウェッジ").replace("左 6.5yd", "右 3.0yd")
    text = SAMPLE + "\nスマッシュ指数: 9.9pt\n\n" + second
    result = parse(text, JST)
    assert [s.club for s in result.shots] == ["7I", "PW"]
    assert result.shots[0].extra == {"スマッシュ指数": "9.9pt"}
    assert result.shots[1].values["offline_yd"] == 3.0
    assert result.unreadable == []


def test_unreadable_lines_are_reported_with_numbers():
    text = "こんにちは\n" + SAMPLE + "\nキャリー 131.4yd\n飛距離: たくさん"
    result = parse(text, JST)
    assert [n for n, _ in result.unreadable] == [1, 8, 9]
    assert len(result.shots) == 1


def test_wrong_unit_is_unreadable():
    _, result = one(SAMPLE.replace("キャリー: 131.4yd", "キャリー: 131.4m"))
    assert [n for n, _ in result.unreadable] == [2]


@pytest.mark.parametrize(
    ("label", "club"),
    [
        ("ドライバー", "1W"),
        ("1W", "1W"),
        ("3ウッド", "3W"),
        ("スプーン", "3W"),
        ("4UT", "4UT"),
        ("ユーティリティ", "UT"),
        ("7アイアン", "7I"),
        ("7番アイアン", "7I"),
        ("７Ｉ", "7I"),
        ("PW", "PW"),
        ("サンドウェッジ", "SW"),
        ("アプローチウェッジ", "AW"),
        ("パター", "PT"),
        ("謎のクラブ", None),
    ],
)
def test_normalize_club(label, club):
    assert normalize_club(label) == club


def test_signs_for_slice_and_out_in():
    text = (
        SAMPLE.replace("左 6.5yd", "右 12.0yd")
        .replace("857rpm（ドロー・左回転）", "1200rpm（スライス・右回転）")
        .replace("5.8°（In-Out）", "4.0°（Out-In）")
        .replace("右 1.9°（Opened）", "右 3.0°（Opened）")
    )
    shot, _ = one(text)
    assert shot.values["offline_yd"] == 12.0
    assert shot.values["sidespin_rpm"] == 1200
    assert shot.values["club_path_deg"] == -4.0
    assert check(shot) == []  # フェース − 軌道 = +7.0、右回転で一致


def test_check_flags():
    text = (
        SAMPLE.replace("飛距離: 149.9yd", "飛距離: 155.0yd")
        .replace("ミート率: 1.40", "ミート率: 1.20")
        .replace("857rpm（ドロー・左回転）", "857rpm（右回転）")
        .replace("右 1.9°（Opened）", "右 1.9°（Closed）")
        .replace("打ち上げ角度(縦): 16.1°", "打ち上げ角度(縦): 61.0°")
    )
    shot, _ = one(text)
    codes = [f.code for f in check(shot)]
    assert codes == ["distance", "smash", "curve", "direction", "range"]


def test_curve_check_skips_nearly_straight_shots():
    text = SAMPLE.replace("5.8°（In-Out）", "1.5°（In-Out）").replace("右 1.9°（Opened）", "右 1.0°（Opened）")
    shot, _ = one(text.replace("857rpm（ドロー・左回転）", "150rpm（右回転）"))
    assert "curve" not in [f.code for f in check(shot)]


def test_missing_direction_and_required_items():
    text = SAMPLE.replace("左 6.5yd", "6.5yd").replace("クラブスピード: 31.6m/s / ", "")
    shot, _ = one(text)
    codes = [f.code for f in check(shot)]
    assert "direction" in codes and "missing" in codes and "smash" not in codes


def test_looks_like_metrics():
    assert looks_like_metrics(SAMPLE)
    assert not looks_like_metrics("2026/10/07 17:09 レッスンでフェースの向きを直した")
    assert not looks_like_metrics("キャリーが伸びない")


@pytest.mark.parametrize(
    ("club", "expected"),
    [("1W", "driver"), ("3W", "wood"), ("4UT", "wood"), ("7I", "iron"), ("PW", "wedge"), ("AW", "wedge"), ("PT", None)],
)
def test_club_groups(club, expected):
    assert group(club) == expected
