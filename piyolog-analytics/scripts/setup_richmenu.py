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

normal mode (Phase 4-B): 8 ボタン
  📊 今日 | 📈 ミルク | 💤 睡眠 | ⚖️ 体重
  📅 週間 | 🔥 ヒートマップ | 💬 相談 | ⚙️ 設定

consulting mode: `💬 相談` を `🚪 相談終了` に差し替えた版。
Phase 4-B で `❓ ヘルプ` を `⚙️ 設定` に置換 (Quick Reply で datetime
picker を出すための entry point)。`ヘルプ` は text コマンドで利用可能。

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
    (220, 220, 220),  # Mute (設定)
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
    CellSpec("設定", "⚙️", "action=settings"),
]

# Phase 3-C: consulting mode 中に表示する 8 ボタン版。「💬 相談」を「🚪 相談終了」に
# 差し替え、それ以外は normal と同じ。consulting 中もサマリ/グラフ参照は可能にする。
CONSULTING_CELLS: list[CellSpec] = [
    CellSpec("今日", "📊", "action=summary&period=today"),
    CellSpec("ミルク", "📈", "action=chart&kind=milk&period=week"),
    CellSpec("睡眠", "💤", "action=chart&kind=sleep&period=week"),
    CellSpec("体重", "⚖️", "action=chart&kind=weight&period=month"),
    CellSpec("週間", "📅", "action=summary&period=week"),
    CellSpec("ヒートマップ", "🔥", "action=chart&kind=heatmap&period=month"),
    CellSpec("相談終了", "🚪", "action=consult&op=exit"),
    CellSpec("設定", "⚙️", "action=settings"),
]

# 日本語ラベル用フォント候補 (mono 描画)。Cloud Run image (Linux) と macOS 両対応。
JP_FONT_CANDIDATES = [
    # Linux (Docker, fonts-noto-cjk apt から)
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    # macOS
    "/System/Library/Fonts/HiraginoSans-W6.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]

# 色付き絵文字フォント。bitmap 形式 (Apple Color Emoji の ttc) は固定サイズで
# しか load できないため、各候補の supported size を併記する。
# Pillow >= 10 の `ImageFont.truetype(... size=...)` + `draw.text(..., embedded_color=True)`
# で描画可能。
COLOR_EMOJI_FONTS: list[tuple[str, int]] = [
    # macOS: Apple Color Emoji.ttc は bitmap font で固定 size しか load できない。
    # 利用可能 size = 20 / 32 / 40 / 48 / 64 / 96。96 が最大。
    ("/System/Library/Fonts/Apple Color Emoji.ttc", 96),
    # Linux: Noto Color Emoji (apt: fonts-noto-color-emoji) は size 109 のみ
    ("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", 109),
    # 古い Debian 命名規則 fallback
    ("/usr/share/fonts/truetype/noto-emoji/NotoColorEmoji.ttf", 109),
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


def _resolve_emoji_font() -> tuple[ImageFont.FreeTypeFont | None, int]:
    """色付き絵文字フォントを返す。見つからなければ (None, 0)。

    bitmap fontの fixed size を併せて返す (描画時の倍率調整用)。
    """
    for path, native_size in COLOR_EMOJI_FONTS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=native_size), native_size
            except OSError:
                continue
    logger.warning("color emoji font not found; icons will be drawn as plain text (□ may appear)")
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
    emoji_font: ImageFont.FreeTypeFont | None,
    emoji_native_size: int,
) -> None:
    """1 セル分を描画 (背景の角丸矩形 + アイコン + ラベル)。

    emoji_font が None なら icon は描画せず、ラベルのみで識別する。
    色付き絵文字は `embedded_color=True` 必須 (Pillow >= 10)。
    """
    pad = 24
    rect = (x + pad, y + pad, x + width - pad, y + height - pad)
    draw.rounded_rectangle(rect, radius=32, fill=color, outline=GRID_COLOR, width=2)

    # アイコン (中央上寄り)
    if emoji_font is not None:
        # bitmap の native size のまま draw → 別 layer に描画後 resize して合成
        # (color bitmap は draw 時に rescale できないため小 image に描いてから resize)
        target_icon_size = 200  # 目標表示サイズ (px)
        scale = target_icon_size / emoji_native_size
        # 一時 RGBA layer に native size で描画
        tmp = Image.new("RGBA", (emoji_native_size * 2, emoji_native_size * 2), (0, 0, 0, 0))
        tmp_draw = ImageDraw.Draw(tmp)
        try:
            tmp_draw.text((0, 0), cell.icon, font=emoji_font, embedded_color=True)
        except Exception:
            # 古い PIL 等で embedded_color が無い場合は plain text fallback
            tmp_draw.text((0, 0), cell.icon, fill=FG_COLOR, font=emoji_font)
        # bbox で実描画範囲を取り、リサイズして合成
        bbox = tmp.getbbox() or (0, 0, emoji_native_size, emoji_native_size)
        cropped = tmp.crop(bbox)
        new_size = (max(1, int(cropped.width * scale)), max(1, int(cropped.height * scale)))
        resized = cropped.resize(new_size, Image.LANCZOS)
        ix = x + (width - resized.width) // 2
        iy = y + height // 2 - resized.height - 20
        img.paste(resized, (ix, iy), resized)

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
    emoji_font, emoji_size = _resolve_emoji_font()

    for idx, cell in enumerate(cells):
        col = idx % GRID_COLS
        row = idx // GRID_COLS
        x = col * CELL_WIDTH
        y = row * CELL_HEIGHT
        _draw_cell(
            img,
            draw,
            x=x,
            y=y,
            width=CELL_WIDTH,
            height=CELL_HEIGHT,
            cell=cell,
            color=CELL_COLORS[idx],
            label_font=label_font,
            emoji_font=emoji_font,
            emoji_native_size=emoji_size,
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


def _build_and_register_one(
    *,
    cells: list[CellSpec],
    name: str,
    image_path: Path,
    access_token: str | None,
    set_as_default: bool,
) -> str | None:
    """1 mode 分の生成 + 登録。dry-run なら画像のみ作って return None。"""
    logger.info("rendering richmenu image '%s' (%dx%d)", name, LARGE_WIDTH, LARGE_HEIGHT)
    img = render_richmenu_image(cells)
    img.save(image_path, format="PNG")
    logger.info("image saved: %s", image_path)
    if access_token is None:
        return None
    payload = build_richmenu_payload(cells, name=f"piyolog_{name}")
    rich_menu_id = create_richmenu(access_token=access_token, payload=payload)
    logger.info("[%s] rich_menu_id=%s", name, rich_menu_id)
    with open(image_path, "rb") as f:
        upload_richmenu_image(
            access_token=access_token,
            rich_menu_id=rich_menu_id,
            image_bytes=f.read(),
        )
    if set_as_default:
        logger.info("[%s] setting as default for all users", name)
        set_default_richmenu(access_token=access_token, rich_menu_id=rich_menu_id)
    return rich_menu_id


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
    parser.add_argument(
        "--mode",
        choices=["normal", "consulting", "both"],
        default="normal",
        help=(
            "生成・登録するメニュー mode。"
            "normal (default): 通常メニューのみ。"
            "consulting: 相談用メニューのみ。"
            "both: 両方を生成・登録 (normal を default として set)。"
        ),
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    access_token: str | None = None
    if not args.dry_run:
        access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
        if not access_token:
            logger.error("LINE_CHANNEL_ACCESS_TOKEN env is required (or use --dry-run)")
            return 2

    output_ids: dict[str, str] = {}
    targets = []
    if args.mode in {"normal", "both"}:
        targets.append(("normal", NORMAL_CELLS, out_dir / "richmenu_normal.png", True))
    if args.mode in {"consulting", "both"}:
        # consulting は default に置かない (普段 normal、enter 時に per-user link)
        targets.append(("consulting", CONSULTING_CELLS, out_dir / "richmenu_consulting.png", False))

    for name, cells, path, set_default in targets:
        rid = _build_and_register_one(
            cells=cells,
            name=name,
            image_path=path,
            access_token=access_token,
            set_as_default=set_default,
        )
        if rid is not None:
            output_ids[name] = rid

    if args.dry_run:
        logger.info("[dry-run] skip LINE API calls")
        return 0

    print()  # ops が grep しやすいよう一行空ける
    for name, rid in output_ids.items():
        print(f"RICH_MENU_ID_{name.upper()}={rid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
