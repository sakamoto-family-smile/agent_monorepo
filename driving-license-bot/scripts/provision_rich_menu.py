"""Rich Menu を作成し、Bot のデフォルトとしてバインドする一発スクリプト。

DESIGN.md §1.3 / §9.1 に対応。Phase 1.5 では「クイズ / モード切替 / 現在のモード /
ヘルプ / データ削除」の 5 ボタン構成。Phase 2 で agent-service が動き始めたら
「復習モード」「模擬試験」を追加する。

使い方:
    cd driving-license-bot
    LINE_CHANNEL_ACCESS_TOKEN=... uv run python scripts/provision_rich_menu.py \
        --image path/to/menu.png \
        [--unbind] [--delete-existing]

リッチメニューの画像（2500x1686 か 2500x843）は別途用意する必要があり、本スクリプト
は画像のアップロードとリッチメニュー定義の登録、Bot へのバインドのみ行う。

LINE Messaging API SDK v3 を直接利用。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    MessagingApiBlob,
    RichMenuArea,
    RichMenuBounds,
    RichMenuRequest,
    RichMenuSize,
)
from linebot.v3.messaging.models import (
    MessageAction,
)


def build_rich_menu_request() -> RichMenuRequest:
    """5 ボタン構成のリッチメニュー定義を返す（2500x843 サイズ）。

    レイアウト:
       ┌──────────┬──────────┬──────────┐
       │ クイズ    │ モード   │ ヘルプ    │
       ├──────────┴──────────┴──────────┤
       │ 現在のモード     │ データ削除   │
       └──────────────────┴────────────┘
    """
    width = 2500
    height = 843

    return RichMenuRequest(
        size=RichMenuSize(width=width, height=height),
        selected=True,
        name="driving-license-bot main menu (Phase 1.5)",
        chatBarText="メニュー",
        areas=[
            # 上段左: クイズ
            RichMenuArea(
                bounds=RichMenuBounds(x=0, y=0, width=width // 3, height=height // 2),
                action=MessageAction(label="クイズ", text="クイズ"),
            ),
            # 上段中: モード切替
            RichMenuArea(
                bounds=RichMenuBounds(
                    x=width // 3, y=0, width=width // 3, height=height // 2
                ),
                action=MessageAction(label="モード切替", text="モード切替"),
            ),
            # 上段右: ヘルプ
            RichMenuArea(
                bounds=RichMenuBounds(
                    x=2 * width // 3, y=0, width=width // 3, height=height // 2
                ),
                action=MessageAction(label="ヘルプ", text="ヘルプ"),
            ),
            # 下段左: 現在のモード
            RichMenuArea(
                bounds=RichMenuBounds(
                    x=0, y=height // 2, width=width // 2, height=height // 2
                ),
                action=MessageAction(label="現在のモード", text="現在のモード"),
            ),
            # 下段右: データを削除
            RichMenuArea(
                bounds=RichMenuBounds(
                    x=width // 2,
                    y=height // 2,
                    width=width // 2,
                    height=height // 2,
                ),
                action=MessageAction(label="データを削除", text="データを削除"),
            ),
        ],
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Provision driving-license-bot rich menu")
    p.add_argument(
        "--image",
        type=Path,
        required=True,
        help="リッチメニュー画像 (PNG, 2500x843)",
    )
    p.add_argument(
        "--delete-existing",
        action="store_true",
        help="既存のリッチメニューを全削除してから作成",
    )
    p.add_argument(
        "--unbind",
        action="store_true",
        help="作成のみ行いデフォルト bind はしない（テスト/ステージング用）",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        print("LINE_CHANNEL_ACCESS_TOKEN env is required", file=sys.stderr)
        return 1
    if not args.image.exists():
        print(f"image not found: {args.image}", file=sys.stderr)
        return 1

    config = Configuration(access_token=token)

    with ApiClient(config) as api_client:
        api = MessagingApi(api_client)
        blob_api = MessagingApiBlob(api_client)

        if args.delete_existing:
            existing = api.get_rich_menu_list()
            for menu in existing.richmenus or []:
                print(f"deleting existing menu: {menu.rich_menu_id}")
                api.delete_rich_menu(menu.rich_menu_id)

        request = build_rich_menu_request()
        created = api.create_rich_menu(request)
        rich_menu_id = created.rich_menu_id
        print(f"created rich menu id: {rich_menu_id}")

        with args.image.open("rb") as f:
            blob_api.set_rich_menu_image(
                rich_menu_id=rich_menu_id,
                body=f.read(),
                _headers={"Content-Type": "image/png"},
            )
        print("uploaded image")

        if not args.unbind:
            api.set_default_rich_menu(rich_menu_id=rich_menu_id)
            print("set as default rich menu")
        else:
            print("skipped default bind (--unbind)")

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
