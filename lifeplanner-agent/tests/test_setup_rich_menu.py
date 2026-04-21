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


def test_build_menu_has_three_equal_buttons():
    menu = sm.build_menu_request(liff_id=None)
    assert menu["size"] == {"width": 2500, "height": 843}
    assert len(menu["areas"]) == 3
    # 3 ボタンの x 座標が 0 / 833 / 1666
    xs = [a["bounds"]["x"] for a in menu["areas"]]
    assert xs == [0, 833, 1666]
    # 最後のボタンだけ残り幅を吸収して幅が +1 等ずれる可能性があるので合計は 2500
    total = sum(a["bounds"]["width"] for a in menu["areas"])
    assert total == 2500


def test_build_menu_without_liff_uses_help_fallback_for_linking():
    menu = sm.build_menu_request(liff_id=None)
    third = menu["areas"][2]
    assert third["action"] == {"type": "message", "text": "/help"}


def test_build_menu_with_liff_uses_uri_action_to_liff_url():
    menu = sm.build_menu_request(liff_id="1234567890-abcdefgh")
    third = menu["areas"][2]
    assert third["action"] == {
        "type": "uri",
        "uri": "https://liff.line.me/1234567890-abcdefgh",
    }


def test_build_menu_scenarios_button_is_message_command():
    menu = sm.build_menu_request(liff_id=None)
    first = menu["areas"][0]
    assert first["action"] == {"type": "message", "text": "/scenarios"}


def test_render_menu_image_returns_valid_png_bytes():
    png = sm.render_menu_image()
    # PNG のマジックナンバー
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    # 32KB 未満程度のサイズ (無意味にでかくないこと)
    assert 1000 < len(png) < 500_000
