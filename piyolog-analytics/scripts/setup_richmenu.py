"""Phase 2: リッチメニュー画像生成 + LINE API への登録 (one-shot ops スクリプト)。

LINE のリッチメニュー仕様:
  画像サイズ: 2500x1686 (大) または 2500x843 (小) px、JPEG / PNG
  領域 (areas): クリックエリアの bounds を JSON で定義し、各エリアごとに
                Postback / message / URI 等の action を設定

本スクリプトは:
  1. Pillow で 4x2 グリッドの 2500x1686 PNG を生成
  2. /v2/bot/richmenu に POST → richMenuId 取得
  3. /v2/bot/richmenu/{id}/content に PUT で画像アップロード
  4. setDefaultRichMenu で全ユーザに紐付け
  5. 標準出力に `RICH_MENU_ID_NORMAL=...` を print

normal mode (Phase 2): 8 ボタン
  📊 今日 | 📈 ミルク | 💤 睡眠 | ⚖️ 体重
  📅 週間 | 🔥 ヒートマップ | 💬 相談 | ❓ ヘルプ

consulting mode (Phase 3 で別途登録、stub のみ): `💬 相談` を `🚪 相談終了` に
差し替えた版。本 PR では生成のみで未使用。

使い方:
  cd piyolog-analytics
  LINE_CHANNEL_ACCESS_TOKEN=$(...) uv run python scripts/setup_richmenu.py

env:
  LINE_CHANNEL_ACCESS_TOKEN: LINE Messaging API のチャンネルアクセストークン
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
GRID_COLS = 4
GRID_ROWS = 2
CELL_WIDTH = LARGE_WIDTH // GRID_COLS  # 625
CELL_HEIGHT = LARGE_HEIGHT // GRID_ROWS  # 843

# ---- テーマ (visualizer.py と揃える Paper Cream パレット) ----
BG_COLOR = (250, 246, 240)  # Paper Cream
FG_COLOR = (43, 40, 37)  # Deep Ink
GRID_COLOR = (232, 226, 216)
CELL_COLORS = [
    (244, 168, 150),  # Peach (今日)
    (244, 168, 150),  # Peach (ミルク)
    (169, 196, 160),  # Sage (睡眠)
    (164, 197, 216),  # Sky (体重)
    (245, 214, 128),  # Butter (週間)
    (245, 214, 128),  # Butter (ヒートマップ)
    (200, 180, 220),  # Lilac (相談)
    (220, 220, 220),  # Mute (ヘルプ)
]


@dataclass(frozen=True)
class CellSpec:
    """1 ボタンの仕様。"""

    label: str
    icon: str  # 絵文字
    postback_data: str  # action=...&kind=...


NORMAL_CELLS: list[CellSpec] = [
    # 上段
    CellSpec("今日", "📊", "action=summary&period=today"),
    CellSpec("ミルク", "📈", "action=chart&kind=milk&period=week"),
    CellSpec("睡眠", "💤", "action=chart&kind=sleep&period=week"),
    CellSpec("体重", "⚖️", "action=chart&kind=weight&period=month"),
    # 下段
    CellSpec("週間", "📅", "action=summary&period=week"),
    CellSpec("ヒートマップ", "🔥", "action=chart&kind=heatmap&period=month"),
    CellSpec("相談", "💬", "action=consult&op=enter"),
    CellSpec("ヘルプ", "❓", "action=help"),
]

# 絵文字描画用フォント候補。Cloud Run image (Linux) と macOS 両対応。
# Linux: fonts-noto-color-emoji が必要 (Dockerfile では未追加。本 PR 範囲外、
# 当面は label の絵文字をフォントで描画せず、絵文字部分は半透明の小サイズ
# (テキスト) としてフォールバック。Noto Sans CJK が絵文字には対応していない
# ため "□" になる可能性あり。実用上は label 文字が読めれば OK)
JP_FONT_CANDIDATES = [
    # Linux (Docker)
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    # macOS
    "/System/Library/Fonts/HiraginoSans-W6.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]


def _resolve_jp_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """利用可能な日本語フォントを順に試す。全て見つからなければ default。"""
    for path in JP_FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    logger.warning("JP font not found in candidates; falling back to default bitmap font")
    return ImageFont.load_default()


def _draw_cell(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    cell: CellSpec,
    color: tuple[int, int, int],
    label_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    icon_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    """1 セル分を描画 (背景の角丸矩形 + アイコン + ラベル)。"""
    pad = 24
    rect = (x + pad, y + pad, x + width - pad, y + height - pad)
    draw.rounded_rectangle(rect, radius=32, fill=color, outline=GRID_COLOR, width=2)
    # アイコン (中央上寄り)
    icon_text = cell.icon
    icon_bbox = draw.textbbox((0, 0), icon_text, font=icon_font)
    icon_w = icon_bbox[2] - icon_bbox[0]
    icon_h = icon_bbox[3] - icon_bbox[1]
    icon_x = x + (width - icon_w) // 2
    icon_y = y + height // 2 - icon_h - 20
    draw.text((icon_x, icon_y), icon_text, fill=FG_COLOR, font=icon_font)
    # ラベル (中央下寄り)
    label_bbox = draw.textbbox((0, 0), cell.label, font=label_font)
    label_w = label_bbox[2] - label_bbox[0]
    label_x = x + (width - label_w) // 2
    label_y = y + height // 2 + 30
    draw.text((label_x, label_y), cell.label, fill=FG_COLOR, font=label_font)


def render_richmenu_image(cells: list[CellSpec]) -> Image.Image:
    """8 ボタンの richmenu 画像を生成して PIL Image で返す。"""
    if len(cells) != GRID_COLS * GRID_ROWS:
        raise ValueError(f"need {GRID_COLS * GRID_ROWS} cells, got {len(cells)}")
    img = Image.new("RGB", (LARGE_WIDTH, LARGE_HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    label_font = _resolve_jp_font(72)
    icon_font = _resolve_jp_font(160)

    for idx, cell in enumerate(cells):
        col = idx % GRID_COLS
        row = idx // GRID_COLS
        x = col * CELL_WIDTH
        y = row * CELL_HEIGHT
        _draw_cell(
            draw,
            x=x,
            y=y,
            width=CELL_WIDTH,
            height=CELL_HEIGHT,
            cell=cell,
            color=CELL_COLORS[idx],
            label_font=label_font,
            icon_font=icon_font,
        )
    return img


def build_richmenu_payload(cells: list[CellSpec], *, name: str = "piyolog_normal") -> dict:
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
                "action": {
                    "type": "postback",
                    "data": cell.postback_data,
                    # displayText: ユーザのトーク画面に「ミルク」等として表示される
                    "displayText": cell.label,
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
    *,
    access_token: str,
    rich_menu_id: str,
    image_bytes: bytes,
    timeout: float = 30.0,
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
        help="LINE API 呼び出しを skip して画像のみ出力 (CI / debug 用)",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    image_path = out_dir / "richmenu_normal.png"

    logger.info("rendering richmenu image (%dx%d)", LARGE_WIDTH, LARGE_HEIGHT)
    img = render_richmenu_image(NORMAL_CELLS)
    img.save(image_path, format="PNG")
    logger.info("image saved: %s", image_path)

    if args.dry_run:
        logger.info("[dry-run] skip LINE API calls")
        return 0

    access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
    if not access_token:
        logger.error("LINE_CHANNEL_ACCESS_TOKEN env is required (or use --dry-run)")
        return 2

    payload = build_richmenu_payload(NORMAL_CELLS)
    logger.info("creating richmenu via LINE API ...")
    rich_menu_id = create_richmenu(access_token=access_token, payload=payload)
    logger.info("rich_menu_id=%s", rich_menu_id)

    logger.info("uploading image to richmenu ...")
    with open(image_path, "rb") as f:
        upload_richmenu_image(
            access_token=access_token,
            rich_menu_id=rich_menu_id,
            image_bytes=f.read(),
        )

    logger.info("setting default richmenu for all users ...")
    set_default_richmenu(access_token=access_token, rich_menu_id=rich_menu_id)

    print()  # ops が grep しやすいよう一行空ける
    print(f"RICH_MENU_ID_NORMAL={rich_menu_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
