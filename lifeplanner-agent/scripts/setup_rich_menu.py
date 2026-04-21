"""LINE Rich Menu を 1 回だけ登録するスクリプト。

構成:
  - サイズ compact (2500x843) を 3 等分し、左から `[シナリオ一覧] [ヘルプ] [連携]` の
    3 ボタンを配置
  - メニュー画像は Pillow で自動生成 (テキスト 3 ブロック)
  - LINE Messaging API の 3 エンドポイントを順に叩き、最後に default rich menu として設定

依存:
  - 環境変数 `LINE_CHANNEL_ACCESS_TOKEN` (必須)
  - 環境変数 `LIFF_ID` (「連携」ボタンの URI に使用。未設定なら連携ボタンは `/help` メッセージに代替)
  - Pillow (dev 依存)

使い方:
  uv run python scripts/setup_rich_menu.py
  uv run python scripts/setup_rich_menu.py --dry-run   # API を叩かず、生成 JSON と画像パスを表示
  uv run python scripts/setup_rich_menu.py --output out.png --dry-run  # 画像だけ確認
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
from pathlib import Path

import httpx

LINE_API = "https://api.line.me"
LINE_DATA_API = "https://api-data.line.me"

WIDTH = 2500
HEIGHT = 843

BG = (30, 64, 175)  # Indigo-ish
FG = (255, 255, 255)

BUTTONS: list[dict] = [
    {"label": "シナリオ一覧", "action_type": "message", "payload": "/scenarios"},
    {"label": "ヘルプ", "action_type": "message", "payload": "/help"},
    # 連携ボタンは build_menu_request() で LIFF_ID に応じて置き換える
    {"label": "連携", "action_type": "placeholder", "payload": ""},
]

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("setup_rich_menu")


# ---------------------------------------------------------------------------
# 画像生成
# ---------------------------------------------------------------------------


def render_menu_image() -> bytes:
    """compact サイズ (2500x843) の 3 等分ボタン画像を PNG バイト列で返す。"""
    try:
        from PIL import Image, ImageDraw
    except ImportError as e:
        raise RuntimeError(
            "Pillow is required. Run `uv sync --dev` to install it."
        ) from e

    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    third = WIDTH // 3
    # 境界線
    for i in (1, 2):
        x = third * i
        draw.line([(x, 30), (x, HEIGHT - 30)], fill=(255, 255, 255, 128), width=4)

    # フォント: プラットフォーム依存で落ちないよう、デフォルト + 大きめビットマップに fallback
    label_font = _load_font(size=96)
    for i, btn in enumerate(BUTTONS):
        label = btn["label"]
        cx = third * i + third // 2
        cy = HEIGHT // 2
        _draw_centered_text(draw, label, cx, cy, label_font)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _load_font(*, size: int):
    from PIL import ImageFont

    # 日本語を表示できる可能性が高いフォント候補を順に試す
    candidates = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",  # macOS
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",  # Linux
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    # どれも無ければ PIL の default (サイズ固定のビットマップ) で妥協
    return ImageFont.load_default()


def _draw_centered_text(draw, text: str, cx: int, cy: int, font) -> None:
    # bbox で中心揃え
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((cx - tw // 2, cy - th // 2), text, fill=FG, font=font)


# ---------------------------------------------------------------------------
# Rich menu JSON
# ---------------------------------------------------------------------------


def build_menu_request(*, liff_id: str | None) -> dict:
    third = WIDTH // 3
    areas: list[dict] = []
    for i, btn in enumerate(BUTTONS):
        if btn["action_type"] == "placeholder":
            # 連携ボタン: LIFF_ID があれば LIFF URL、無ければ /help への message
            if liff_id:
                action = {
                    "type": "uri",
                    "uri": f"https://liff.line.me/{liff_id}",
                }
            else:
                action = {"type": "message", "text": "/help"}
        elif btn["action_type"] == "message":
            action = {"type": "message", "text": btn["payload"]}
        else:
            raise ValueError(f"Unknown action_type: {btn['action_type']}")
        areas.append(
            {
                "bounds": {
                    "x": third * i,
                    "y": 0,
                    "width": third if i < 2 else WIDTH - third * 2,
                    "height": HEIGHT,
                },
                "action": action,
            }
        )

    return {
        "size": {"width": WIDTH, "height": HEIGHT},
        "selected": True,
        "name": "LifePlanner default menu",
        "chatBarText": "メニュー",
        "areas": areas,
    }


# ---------------------------------------------------------------------------
# LINE API calls
# ---------------------------------------------------------------------------


def _auth_headers(token: str, *, json_body: bool = True) -> dict:
    h = {"Authorization": f"Bearer {token}"}
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def create_rich_menu(client: httpx.Client, token: str, menu: dict) -> str:
    r = client.post(
        f"{LINE_API}/v2/bot/richmenu",
        headers=_auth_headers(token),
        json=menu,
        timeout=30.0,
    )
    if r.status_code != 200:
        raise RuntimeError(f"create_rich_menu failed: {r.status_code} {r.text}")
    return r.json()["richMenuId"]


def upload_rich_menu_image(
    client: httpx.Client, token: str, menu_id: str, png_bytes: bytes
) -> None:
    r = client.post(
        f"{LINE_DATA_API}/v2/bot/richmenu/{menu_id}/content",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "image/png",
        },
        content=png_bytes,
        timeout=60.0,
    )
    if r.status_code != 200:
        raise RuntimeError(
            f"upload_rich_menu_image failed: {r.status_code} {r.text}"
        )


def set_default_rich_menu(client: httpx.Client, token: str, menu_id: str) -> None:
    r = client.post(
        f"{LINE_API}/v2/bot/user/all/richmenu/{menu_id}",
        headers=_auth_headers(token, json_body=False),
        timeout=30.0,
    )
    if r.status_code != 200:
        raise RuntimeError(
            f"set_default_rich_menu failed: {r.status_code} {r.text}"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="LINE API を叩かず、生成 JSON と画像を保存するだけ",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("logs/rich-menu.png"),
        help="--dry-run 時に画像を書き出すパス",
    )
    args = parser.parse_args()

    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    liff_id = os.environ.get("LIFF_ID", "")
    if not token and not args.dry_run:
        logger.error(
            "LINE_CHANNEL_ACCESS_TOKEN が未設定です。.env を読み込むか、"
            "--dry-run で動作確認してください。"
        )
        return 2

    menu = build_menu_request(liff_id=liff_id or None)
    logger.info(
        "Menu JSON を生成しました (areas=%d, LIFF=%s)",
        len(menu["areas"]),
        "有効" if liff_id else "無効 (連携ボタンは /help にフォールバック)",
    )
    logger.debug("Menu JSON: %s", json.dumps(menu, ensure_ascii=False, indent=2))

    image = render_menu_image()
    logger.info("画像を生成しました (%d bytes)", len(image))

    if args.dry_run:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(image)
        logger.info("dry-run: 画像を %s に書き出しました", args.output)
        print(json.dumps(menu, ensure_ascii=False, indent=2))
        return 0

    with httpx.Client() as client:
        menu_id = create_rich_menu(client, token, menu)
        logger.info("Rich menu を作成しました: id=%s", menu_id)
        upload_rich_menu_image(client, token, menu_id, image)
        logger.info("画像をアップロードしました")
        set_default_rich_menu(client, token, menu_id)
        logger.info("default rich menu として設定しました")

    print(f"rich_menu_id={menu_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
