"""ライフイベントの一括投入スクリプト (PR 1)。

JSON ファイル (例: data/seeds/example_events.json) を読み、指定 scenario に
LifeEvent レコードを追加する。既存 scenario への追記モードと、空にしてから
入れ替える置換モードがある。

設計判断:
  - DB 直接 (SQLAlchemy AsyncSession) で投入する。HTTP 経由より安定。
  - validation 失敗の event は skip ではなく fail-fast (途中で止まる)。
  - dry-run で投入前に内容を確認できる。

使い方:
  cd lifeplanner-agent
  uv run python scripts/seed_events.py \
      --scenario-id 1 \
      --file data/seeds/example_events.json

  # 既存イベントを全削除してから入れ替え:
  uv run python scripts/seed_events.py --scenario-id 1 --file <path> --replace

  # 投入せず内容のみ確認:
  uv run python scripts/seed_events.py --scenario-id 1 --file <path> --dry-run

env:
  DATABASE_URL: SQLAlchemy URL (lifeplanner-agent と同じ)
                空なら .env or sqlite ローカルが使われる
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# app/ を sys.path に追加 (lifeplanner-agent ルート想定)
_APP_DIR = Path(__file__).resolve().parent.parent / "app"
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from models.db import LifeEvent  # noqa: E402
from repositories.scenario import add_event, get_scenario  # noqa: E402
from services.database import close_db, get_session_factory  # noqa: E402
from sqlalchemy import delete  # noqa: E402

logger = logging.getLogger("seed_events")
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


_REQUIRED_FIELDS = ("event_type", "start_year")
_SUPPORTED_EVENTS = ("E01", "E02", "E04")


def _validate(events: list[dict]) -> None:
    for i, ev in enumerate(events):
        for f in _REQUIRED_FIELDS:
            if f not in ev:
                raise ValueError(f"events[{i}] missing required field: {f}")
        if ev["event_type"] not in _SUPPORTED_EVENTS:
            raise ValueError(
                f"events[{i}] unsupported event_type: {ev['event_type']!r} "
                f"(supported: {_SUPPORTED_EVENTS}; E03/E05-E12 は PR 5)"
            )
        if not isinstance(ev["start_year"], int):
            raise ValueError(f"events[{i}].start_year must be int")
        if not isinstance(ev.get("params", {}), dict):
            raise ValueError(f"events[{i}].params must be dict")


async def _seed(
    *, scenario_id: int, events: list[dict], replace: bool, dry_run: bool
) -> int:
    """events を DB に投入。戻り値は投入件数。"""
    factory = get_session_factory()
    try:
        async with factory() as session:
            scenario = await get_scenario(session, scenario_id)
            if scenario is None:
                logger.error("scenario_id=%d not found", scenario_id)
                return -1
            logger.info(
                "target scenario: id=%d household=%s name=%r",
                scenario.id,
                scenario.household_id,
                scenario.name,
            )

            if dry_run:
                for ev in events:
                    logger.info(
                        "[dry-run] would add: type=%s year=%d params=%s",
                        ev["event_type"],
                        ev["start_year"],
                        json.dumps(ev.get("params", {}), ensure_ascii=False),
                    )
                return len(events)

            if replace:
                deleted = await session.execute(
                    delete(LifeEvent).where(LifeEvent.scenario_id == scenario_id)
                )
                logger.info("replace: deleted %d existing events", deleted.rowcount or 0)

            for ev in events:
                await add_event(
                    session,
                    scenario_id=scenario_id,
                    event_type=ev["event_type"],
                    start_year=ev["start_year"],
                    params=ev.get("params", {}),
                )
            await session.commit()
        return len(events)
    finally:
        await close_db()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-id", type=int, required=True)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="既存イベントを削除してから投入 (default: 追記)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="DB を更新せず内容のみ表示"
    )
    args = parser.parse_args(argv)

    if not args.file.exists():
        logger.error("file not found: %s", args.file)
        return 2

    with args.file.open("r", encoding="utf-8") as f:
        data = json.load(f)
    events = data.get("events", [])
    if not isinstance(events, list) or not events:
        logger.error("no events in file (expected key 'events': list)")
        return 2

    try:
        _validate(events)
    except ValueError as e:
        logger.error("validation failed: %s", e)
        return 2

    count = asyncio.run(
        _seed(
            scenario_id=args.scenario_id,
            events=events,
            replace=args.replace,
            dry_run=args.dry_run,
        )
    )
    if count < 0:
        return 3
    if args.dry_run:
        logger.info("[dry-run] would have inserted %d events", count)
    else:
        logger.info("inserted %d events into scenario %d", count, args.scenario_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
