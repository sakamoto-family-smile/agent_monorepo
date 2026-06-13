"""setup_richmenu の payload 生成 unit テスト (画像描画・LINE API は対象外)。"""

from __future__ import annotations

import sys
from pathlib import Path

# scripts/ は package ではないので path を通して import する
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from setup_richmenu import (  # noqa: E402
    CELLS,
    GRID_COLS,
    GRID_ROWS,
    LARGE_HEIGHT,
    LARGE_WIDTH,
    build_richmenu_payload,
)


def test_cells_count_matches_grid():
    assert len(CELLS) == GRID_COLS * GRID_ROWS == 6


def test_payload_shape_and_bounds():
    payload = build_richmenu_payload(CELLS)
    assert payload["size"] == {"width": LARGE_WIDTH, "height": LARGE_HEIGHT}
    assert payload["chatBarText"] == "メニュー"
    areas = payload["areas"]
    assert len(areas) == 6
    # 全エリアが画像内に収まり、message action を持つ
    for a in areas:
        b = a["bounds"]
        assert 0 <= b["x"] and b["x"] + b["width"] <= LARGE_WIDTH
        assert 0 <= b["y"] and b["y"] + b["height"] <= LARGE_HEIGHT
        assert a["action"]["type"] == "message"
        assert a["action"]["text"]


def test_payload_actions_map_to_existing_commands():
    """各ボタンの送信テキストが既存コマンド (line_handler が解釈可能) であること。"""
    payload = build_richmenu_payload(CELLS)
    texts = [a["action"]["text"] for a in payload["areas"]]
    assert texts == [
        "分析",
        "おすすめ",
        "マイリスト",
        "スクリーニング",
        "スクリーニング US",
        "ヘルプ",
    ]
