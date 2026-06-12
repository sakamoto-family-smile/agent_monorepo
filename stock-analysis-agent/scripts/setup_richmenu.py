"""リッチメニュー画像生成 + LINE API への登録 (one-shot ops スクリプト)。

piyolog-analytics/scripts/setup_richmenu.py を stock-analysis-agent 向けに移植。

LINE のリッチメニュー仕様:
  画像サイズ: 2500x1686 (大) px、JPEG / PNG
  領域 (areas): クリックエリアの bounds を JSON で定義し、各エリアに action を設定

stock 版の設計:
  - 3x2 の 6 ボタン。action は **message** (タップで既存テキストコマンドを送る)
    のため、Bot 側のコード変更は不要。
  - 📊 分析     → 「分析」(使い方が返る)   💹 おすすめ → 「おすすめ」
    🔍 日本株    → 「スクリーニング」      🇺🇸 米国株  → 「スクリーニング US」
    🪪 ID       → 「ID」(利用登録用)       ❓ ヘルプ   → 「ヘルプ」

本スクリプトは:
  1. Pillow で 3x2 グリッドの 2500x1686 PNG を生成
  2. /v2/bot/richmenu に POST → richMenuId 取得
  3. /v2/bot/richmenu/{id}/content に PUT で画像アップロード
  4. setDefaultRichMenu で全ユーザに紐付け

使い方:
  cd stock-analysis-agent
  LINE_CHANNEL_ACCESS_TOKEN=$(gcloud secrets versions access latest \
      --secret=stock-analysis-line-line-channel-access-token \
      --project=sakamomo-family-agent) \
    uv run python scripts/setup_richmenu.py

env:
  LINE_CHANNEL_ACCESS_TOKEN: LINE Messaging API のチャネルアクセストークン
  RICHMENU_OUTPUT_DIR (任意): 画像の保存先 (default: data/richmenu)
  RICHMENU_DRY_RUN (任意): true なら API 呼び出しを skip して画像のみ出力
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("setup_richmenu")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

# ---- LINE rich menu 仕様 ----

LARGE_WIDTH = 2500
LARGE_HEIGHT = 1686
GRID_COLS = 3
GRID_ROWS = 2
CELL_WIDTH = LARGE_WIDTH // GRID_COLS  # 833
CELL_HEIGHT = LARGE_HEIGHT // GRID_ROWS  # 843

# ---- テーマ (line_flex.py のヘッダ色 #1E40AF 系に揃えた寒色パレット) ----
BG_COLOR = (245, 247, 250)  # 淡いブルーグレー
FG_COLOR = (30, 41, 59)  # Slate Ink
GRID_COLOR = (203, 213, 225)
CELL_COLORS = [
    (147, 178, 235),  # 分析 (primary blue)
    (134, 200, 188),  # おすすめ (teal)
    (172, 196, 152),  # 日本株 (sage)
    (244, 190, 126),  # 米国株 (amber)
    (196, 181, 224),  # ID (lilac)
    (209, 213, 219),  # ヘルプ (mute)
]


@dataclass(frozen=True)
class CellSpec:
    """1 ボタンの仕様。message action でテキストコマンドを送る。"""

    label: str
    icon: str  # 絵文字
    message_text: str  # タップで送信されるテキスト


CELLS: list[CellSpec] = [
    # 上段
    CellSpec("分析", "📊", "分析"),
    CellSpec("おすすめ", "💹", "おすすめ"),
    CellSpec("日本株スクリーニング", "🔍", "スクリーニング"),
    # 下段
    CellSpec("米国株スクリーニング", "🌎", "スクリーニング US"),
    CellSpec("ID", "🪪", "ID"),
    CellSpec("ヘルプ", "❓", "ヘルプ"),
]

# 日本語ラベル用フォント候補 (Linux / macOS 両対応)。
JP_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/HiraginoSans-W6.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]

# 色付き絵文字フォント (bitmap 形式は固定サイズでしか load できない)。
COLOR_EMOJI_FONTS: list[tuple[str, int]] = [
    ("/System/Library/Fonts/Apple Color Emoji.ttc", 96),
    ("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", 109),
    ("/usr/share/fonts/truetype/noto-emoji/NotoColorEmoji.ttf", 109),
]


def _resolve_jp_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in JP_FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    logger.warning("JP font not found; falling back to default bitmap font")
    return ImageFont.load_default()


def _resolve_emoji_font() -> tuple[ImageFont.FreeTypeFont | None, int]:
    for path, native_size in COLOR_EMOJI_FONTS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=native_size), native_size
            except OSError:
                continue
    logger.warning("color emoji font not found; icons will be skipped")
    return None, 0


def _draw_cell(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    cell: CellSpec,
    color: tuple[int, int, int],
    label_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    small_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    emoji_font: ImageFont.FreeTypeFont | None,
    emoji_native_size: int,
) -> None:
    """1 セル分を描画 (背景の角丸矩形 + アイコン + ラベル)。"""
    pad = 24
    rect = (x + pad, y + pad, x + width - pad, y + height - pad)
    draw.rounded_rectangle(rect, radius=32, fill=color, outline=GRID_COLOR, width=2)

    # アイコン (中央上寄り)。color bitmap は rescale 不可のため別 layer に描いて resize。
    if emoji_font is not None:
        target_icon_size = 200
        scale = target_icon_size / emoji_native_size
        tmp = Image.new("RGBA", (emoji_native_size * 2, emoji_native_size * 2), (0, 0, 0, 0))
        tmp_draw = ImageDraw.Draw(tmp)
        try:
            tmp_draw.text((0, 0), cell.icon, font=emoji_font, embedded_color=True)
        except Exception:
            tmp_draw.text((0, 0), cell.icon, fill=FG_COLOR, font=emoji_font)
        bbox = tmp.getbbox() or (0, 0, emoji_native_size, emoji_native_size)
        cropped = tmp.crop(bbox)
        new_size = (max(1, int(cropped.width * scale)), max(1, int(cropped.height * scale)))
        resized = cropped.resize(new_size, Image.LANCZOS)
        ix = x + (width - resized.width) // 2
        iy = y + height // 2 - resized.height + 40
        img.paste(resized, (ix, iy), resized)

    # ラベル (中央下寄り)。長いラベルは小さいフォントで。
    font = label_font if len(cell.label) <= 6 else small_font
    label_bbox = draw.textbbox((0, 0), cell.label, font=font)
    label_w = label_bbox[2] - label_bbox[0]
    label_x = x + (width - label_w) // 2
    label_y = y + height // 2 + 90
    draw.text((label_x, label_y), cell.label, fill=FG_COLOR, font=font)


def render_richmenu_image(cells: list[CellSpec]) -> Image.Image:
    """6 ボタンの richmenu 画像を生成して PIL Image で返す。"""
    if len(cells) != GRID_COLS * GRID_ROWS:
        raise ValueError(f"need {GRID_COLS * GRID_ROWS} cells, got {len(cells)}")
    img = Image.new("RGB", (LARGE_WIDTH, LARGE_HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    label_font = _resolve_jp_font(80)
    small_font = _resolve_jp_font(56)
    emoji_font, emoji_size = _resolve_emoji_font()

    for idx, cell in enumerate(cells):
        col = idx % GRID_COLS
        row = idx // GRID_COLS
        _draw_cell(
            img,
            draw,
            x=col * CELL_WIDTH,
            y=row * CELL_HEIGHT,
            width=CELL_WIDTH,
            height=CELL_HEIGHT,
            cell=cell,
            color=CELL_COLORS[idx],
            label_font=label_font,
            small_font=small_font,
            emoji_font=emoji_font,
            emoji_native_size=emoji_size,
        )
    return img


def build_richmenu_payload(
    cells: list[CellSpec], *, name: str = "stock_analysis_main"
) -> dict:
    """LINE richmenu 作成 API に投げる JSON payload を生成。"""
    areas = []
    for idx, cell in enumerate(cells):
        col = idx % GRID_COLS
        row = idx // GRID_COLS
        areas.append(
            {
                "bounds": {
                    "x": col * CELL_WIDTH,
                    "y": row * CELL_HEIGHT,
                    "width": CELL_WIDTH,
                    "height": CELL_HEIGHT,
                },
                # message action: タップでそのままテキストコマンドが送信される
                "action": {
                    "type": "message",
                    "label": cell.label[:20],
                    "text": cell.message_text,
                },
            }
        )
    return {
        "size": {"width": LARGE_WIDTH, "height": LARGE_HEIGHT},
        "selected": True,
        "name": name,
        "chatBarText": "メニュー",
        "areas": areas,
    }


# ---- LINE API クライアント ----

LINE_API_BASE = "https://api.line.me/v2/bot"
LINE_CONTENT_API_BASE = "https://api-data.line.me/v2/bot"


def create_richmenu(*, access_token: str, payload: dict, timeout: float = 20.0) -> str:
    resp = httpx.post(
        f"{LINE_API_BASE}/richmenu",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        content=json.dumps(payload),
        timeout=timeout,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"create richmenu failed: {resp.status_code} {resp.text}")
    return resp.json()["richMenuId"]


def upload_richmenu_image(
    *, access_token: str, rich_menu_id: str, image_bytes: bytes, timeout: float = 30.0
) -> None:
    resp = httpx.post(
        f"{LINE_CONTENT_API_BASE}/richmenu/{rich_menu_id}/content",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "image/png",
        },
        content=image_bytes,
        timeout=timeout,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"upload richmenu image failed: {resp.status_code} {resp.text}")


def set_default_richmenu(*, access_token: str, rich_menu_id: str, timeout: float = 10.0) -> None:
    resp = httpx.post(
        f"{LINE_API_BASE}/user/all/richmenu/{rich_menu_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=timeout,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"set default richmenu failed: {resp.status_code} {resp.text}")


# ---- main ----


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("RICHMENU_OUTPUT_DIR", "data/richmenu"),
        help="生成した PNG の保存先 (default: data/richmenu)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=os.environ.get("RICHMENU_DRY_RUN", "").lower() == "true",
        help="LINE API 呼び出しを skip して画像のみ出力 (debug 用)",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    image_path = out_dir / "richmenu_main.png"

    logger.info("rendering richmenu image (%dx%d)", LARGE_WIDTH, LARGE_HEIGHT)
    img = render_richmenu_image(CELLS)
    img.save(image_path, format="PNG")
    logger.info("image saved: %s", image_path)

    if args.dry_run:
        logger.info("[dry-run] skip LINE API calls")
        return 0

    access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
    if not access_token:
        logger.error("LINE_CHANNEL_ACCESS_TOKEN env is required (or use --dry-run)")
        return 2

    payload = build_richmenu_payload(CELLS)
    rich_menu_id = create_richmenu(access_token=access_token, payload=payload)
    logger.info("rich_menu_id=%s", rich_menu_id)
    with open(image_path, "rb") as f:
        upload_richmenu_image(
            access_token=access_token, rich_menu_id=rich_menu_id, image_bytes=f.read()
        )
    set_default_richmenu(access_token=access_token, rich_menu_id=rich_menu_id)
    logger.info("done: rich menu set as default for all users")
    print(f"RICH_MENU_ID={rich_menu_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
