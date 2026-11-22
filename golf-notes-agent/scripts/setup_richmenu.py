"""リッチメニューを作って、全員 (= 自分) の既定にする。メニューを変えたら動かし直す。

    uv run python scripts/setup_richmenu.py [--dry-run] [--keep-old]

config/local.env の LINE_CHANNEL_ACCESS_TOKEN を使う。
1. config/richmenu/richmenu.json でリッチメニューを作る
2. config/richmenu/richmenu.png をアップロードする (1MB まで)
3. 既定のリッチメニューにする
4. 同じ名前の古いリッチメニューを消す (--keep-old で残す)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
MENU = ROOT / "config" / "richmenu" / "richmenu.json"
IMAGE = ROOT / "config" / "richmenu" / "richmenu.png"
ENV = ROOT / "config" / "local.env"
API = "https://api.line.me/v2/bot"
DATA_API = "https://api-data.line.me/v2/bot"
MAX_IMAGE_BYTES = 1024 * 1024


def read_token(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "LINE_CHANNEL_ACCESS_TOKEN" and value.strip():
            return value.strip()
    sys.exit(f"LINE_CHANNEL_ACCESS_TOKEN が {path} にありません")


def check(res: httpx.Response) -> dict:
    if res.status_code >= 400:
        sys.exit(f"LINE API {res.status_code}: {res.text[:300]}")
    return res.json() if res.content else {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="定義と画像を確かめるだけ (API を呼ばない)")
    parser.add_argument("--keep-old", action="store_true")
    args = parser.parse_args()

    menu = json.loads(MENU.read_text(encoding="utf-8"))
    image = IMAGE.read_bytes()
    if len(image) > MAX_IMAGE_BYTES:
        sys.exit(f"{IMAGE.name} が 1MB を超えています ({len(image)} bytes)")
    print(f"menu: {menu['name']} ({len(menu['areas'])} areas), image: {len(image) // 1024} KB")
    if args.dry_run:
        return

    headers = {"Authorization": f"Bearer {read_token(ENV)}"}
    with httpx.Client(timeout=30) as client:
        check(client.post(f"{API}/richmenu/validate", json=menu, headers=headers))
        menu_id = check(client.post(f"{API}/richmenu", json=menu, headers=headers))["richMenuId"]
        check(
            client.post(
                f"{DATA_API}/richmenu/{menu_id}/content",
                content=image,
                headers={**headers, "Content-Type": "image/png"},
            )
        )
        check(client.post(f"{API}/user/all/richmenu/{menu_id}", headers=headers))
        print(f"default rich menu: {menu_id}")
        if args.keep_old:
            return
        for old in check(client.get(f"{API}/richmenu/list", headers=headers)).get("richmenus", []):
            if old["name"] == menu["name"] and old["richMenuId"] != menu_id:
                check(client.delete(f"{API}/richmenu/{old['richMenuId']}", headers=headers))
                print(f"deleted old rich menu: {old['richMenuId']}")


if __name__ == "__main__":
    main()
