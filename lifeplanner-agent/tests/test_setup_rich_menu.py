"""`scripts/setup_rich_menu.py` の純関数 (ネットワーク非依存) をユニットテスト。

生成 JSON の構造と LIFF_ID 有無による「連携」ボタンの分岐を検証する。
画像生成も呼出可能であることだけ確認する (サイズ + PNG ヘッダ)。
"""

from __future__ import annotations

import sys
from pathlib import Path

# スクリプトを test から import するため sys.path に追加
_SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import setup_rich_menu as sm  # noqa: E402


def test_build_menu_has_six_buttons_3x2_grid():
    """PR 2 で 6 ボタン (3x2 grid) に拡張。"""
    menu = sm.build_menu_request(liff_id=None)
    assert menu["size"] == {"width": 2500, "height": 1686}
    assert len(menu["areas"]) == 6
    # 上段 3 ボタン (y=0)、下段 3 ボタン (y=843)
    rows = {area["bounds"]["y"] for area in menu["areas"]}
    assert rows == {0, 843}
    # 各列の x 座標が 0 / 833 / 1666
    top_row_xs = sorted(
        a["bounds"]["x"] for a in menu["areas"] if a["bounds"]["y"] == 0
    )
    assert top_row_xs == [0, 833, 1666]
    # 横方向の合計幅は 2500 (最右列が誤差吸収)
    total_top = sum(
        a["bounds"]["width"] for a in menu["areas"] if a["bounds"]["y"] == 0
    )
    assert total_top == 2500


def test_build_menu_without_liff_uses_help_fallback_for_linking():
    menu = sm.build_menu_request(liff_id=None)
    # 連携ボタンは BUTTONS の placeholder なので index で特定 (PR 2: index=4)
    link_btn = menu["areas"][4]
    assert link_btn["action"] == {"type": "message", "text": "/help"}


def test_build_menu_with_liff_uses_uri_action_to_liff_url():
    menu = sm.build_menu_request(liff_id="1234567890-abcdefgh")
    link_btn = menu["areas"][4]
    assert link_btn["action"] == {
        "type": "uri",
        "uri": "https://liff.line.me/1234567890-abcdefgh",
    }


def test_build_menu_includes_pr2_analysis_buttons():
    """PR 2: 上段 3 ボタンが /summary /networth /anomalies。"""
    menu = sm.build_menu_request(liff_id=None)
    actions_top_row = [
        a["action"]["text"]
        for a in menu["areas"]
        if a["bounds"]["y"] == 0 and a["action"]["type"] == "message"
    ]
    assert "/summary" in actions_top_row
    assert "/networth" in actions_top_row
    assert "/anomalies" in actions_top_row


def test_build_menu_scenarios_button_is_message_command():
    """PR 2: シナリオボタンは下段の最初 (index=3)。"""
    menu = sm.build_menu_request(liff_id=None)
    scenarios_btn = menu["areas"][3]
    assert scenarios_btn["action"] == {"type": "message", "text": "/scenarios"}


def test_render_menu_image_returns_valid_png_bytes():
    png = sm.render_menu_image()
    # PNG のマジックナンバー
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    # 32KB 未満程度のサイズ (無意味にでかくないこと)
    assert 1000 < len(png) < 500_000
