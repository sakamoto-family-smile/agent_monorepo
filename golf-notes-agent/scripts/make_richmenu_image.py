"""リッチメニューの画像 (2500×1686、2 行 × 3 列) を作る。ホストで 1 回だけ動かす。

    uv run --with pillow python scripts/make_richmenu_image.py [--font <日本語フォント>]

ボタンの並びと文言は config/richmenu/richmenu.json の areas と同じ順にする。
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "config" / "richmenu" / "richmenu.png"
DEFAULT_FONT = "/Library/Fonts/Arial Unicode.ttf"
WIDTH, HEIGHT = 2500, 1686
XS = (0, 833, 1667, 2500)
YS = (0, 843, 1686)
# (見出し, 説明, 背景色)。areas と同じ順
BUTTONS = (
    ("メモ", "気づきを送る", "#1f6f50"),
    ("計測", "計測テキストを貼る", "#1d4e89"),
    ("動画", "アングル・クラブを選ぶ", "#7a3b69"),
    ("開始 / 終了", "練習・レッスン・ラウンド", "#8a5a00"),
    ("スコア", "ラウンドのスコア", "#2f5d2f"),
    ("振り返り", "準備中", "#4a4a4a"),
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--font", default=DEFAULT_FONT)
    args = parser.parse_args()
    title_font = ImageFont.truetype(args.font, 150)
    sub_font = ImageFont.truetype(args.font, 58)
    img = Image.new("RGB", (WIDTH, HEIGHT), "#ffffff")
    draw = ImageDraw.Draw(img)
    for i, (title, sub, color) in enumerate(BUTTONS):
        row, col = divmod(i, 3)
        box = (XS[col] + 8, YS[row] + 8, XS[col + 1] - 8, YS[row + 1] - 8)
        draw.rounded_rectangle(box, radius=48, fill=color)
        cx = (box[0] + box[2]) / 2
        cy = (box[1] + box[3]) / 2
        draw.text((cx, cy - 60), title, font=title_font, fill="#ffffff", anchor="mm")
        draw.text((cx, cy + 110), sub, font=sub_font, fill="#e8e8e8", anchor="mm")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, optimize=True)
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
