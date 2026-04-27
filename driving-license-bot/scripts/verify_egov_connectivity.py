"""e-Gov 法令検索 API への到達性をスモークチェックする CLI（手動検証用）。

使い方:
    cd driving-license-bot
    uv run python scripts/verify_egov_connectivity.py             # health のみ
    uv run python scripts/verify_egov_connectivity.py --law 335AC0000000105

Phase 2-F は宣言的セットアップのため、本スクリプトはローカルから手動実行する。
本番では Cloud Monitoring の uptime check で代替。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app.integrations import EgovLawClient, EgovLawError


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Verify e-Gov API connectivity")
    p.add_argument(
        "--law",
        default=None,
        help="特定の law_id の本文を取得（例: 335AC0000000105 = 道路交通法）",
    )
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


async def _run(args: argparse.Namespace) -> int:
    client = EgovLawClient()

    print("[verify_egov] health_check ...")
    healthy = await client.health_check()
    print(f"[verify_egov] health_check → {'OK' if healthy else 'NG'}")
    if not healthy:
        return 2

    if args.law:
        print(f"[verify_egov] fetching law_id={args.law} ...")
        try:
            text = await client.fetch_law_text(args.law)
        except EgovLawError as exc:
            print(f"[verify_egov] FAIL: {exc}", file=sys.stderr)
            return 3
        size = len(text)
        head = text[:200].replace("\n", " ")
        print(f"[verify_egov] OK: fetched {size} bytes")
        print(f"[verify_egov] head: {head}...")

    return 0


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    return asyncio.run(_run(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
