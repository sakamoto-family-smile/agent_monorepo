"""原本から派生データを作り直す CLI (§4.6)。backend のコンテナの中で動かす (make reprocess)。

    python -m app.reprocess lesson [--since YYYY-MM-DD] [--dry-run]
        計測テキスト (lesson_captures.raw_text) をいまのパーサで読み直し、launch_metrics を置き換える
    python -m app.reprocess raw [--dry-run]
        data/raw/ の原本のうち raw_events に無いもの (処理の途中で失敗したイベント) を取り込む

golf.db はホストから開かない。同じコンテナの中なら backend と同時に動いても SQLite のロックが効く
(busy_timeout で待つ)。--dry-run は変わるものを表示するだけで DB を変えない。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from app.config import Settings
from app.lesson.checks import check
from app.lesson.parser import COLUMNS, PARSER_VERSION, parse
from app.line.events import parse_event
from app.storage.db import BUSY_TIMEOUT_MS
from app.storage.tables import launch_metrics, lesson_captures, raw_events
from app.timeutil import from_ms, iso


@dataclass(frozen=True)
class LessonChange:
    capture_id: int
    before: int
    after: int
    changed: bool
    status: str


def _engine(settings: Settings) -> sa.Engine:
    return sa.create_engine(
        f"sqlite:///{settings.paths.db}", connect_args={"timeout": BUSY_TIMEOUT_MS / 1000}
    )


def _rows(shots, flags) -> list[dict]:  # parser.Shot / checks.Flag の list
    return [
        {
            "shot_no": shot.shot_no,
            "shot_at": iso(shot.shot_at),
            "club": shot.club,
            **{c: shot.values.get(c) for c in COLUMNS},
            "labels_json": json.dumps({"club": shot.club_label, **shot.labels}, ensure_ascii=False),
            "extra_json": json.dumps(shot.extra, ensure_ascii=False),
            "check_flags": json.dumps([f.code for f in shot_flags]),
        }
        for shot, shot_flags in zip(shots, flags, strict=True)
    ]


def _comparable(row: dict) -> tuple:
    keys = ("shot_no", "shot_at", "club", *COLUMNS, "labels_json", "extra_json", "check_flags")
    return tuple(row.get(k) for k in keys)


def _next_status(old_status: str, old_flagged: bool, new_flagged: bool) -> str:
    """取り消したものはそのまま。検算 OK なら確定。引っかかる球があれば、人が確定済みのときだけ確定のまま。"""
    if old_status == "rejected":
        return "rejected"
    if not new_flagged:
        return "confirmed"
    return "confirmed" if old_status == "confirmed" and old_flagged else "pending"


def reprocess_lessons(conn: Connection, settings: Settings, since: str | None, dry_run: bool) -> list[LessonChange]:
    query = sa.select(lesson_captures).where(
        lesson_captures.c.source == "text", lesson_captures.c.deleted_at.is_(None)
    )
    if since:
        query = query.where(lesson_captures.c.created_at >= since)
    changes: list[LessonChange] = []
    for cap in conn.execute(query.order_by(lesson_captures.c.id)).all():
        result = parse(cap.raw_text, settings.tz)
        flags = [check(s) for s in result.shots]
        new_rows = _rows(result.shots, flags)
        old_rows = [
            dict(r._mapping)
            for r in conn.execute(
                sa.select(launch_metrics).where(launch_metrics.c.capture_id == cap.id).order_by(launch_metrics.c.shot_no)
            ).all()
        ]
        changed = [_comparable(r) for r in old_rows] != [_comparable(r) for r in new_rows]
        old_flagged = any(json.loads(r["check_flags"]) for r in old_rows)
        status = _next_status(cap.status, old_flagged, any(flags))
        changes.append(LessonChange(cap.id, len(old_rows), len(new_rows), changed, status))
        if dry_run or (not changed and status == cap.status and cap.parser_version == PARSER_VERSION):
            continue
        conn.execute(sa.delete(launch_metrics).where(launch_metrics.c.capture_id == cap.id))
        for row in new_rows:
            conn.execute(sa.insert(launch_metrics).values(capture_id=cap.id, **row))
        conn.execute(
            sa.update(lesson_captures)
            .where(lesson_captures.c.id == cap.id)
            .values(parser_version=PARSER_VERSION, status=status)
        )
    return changes


def import_missing_raw(conn: Connection, settings: Settings, dry_run: bool) -> list[Path]:
    known = {r[0] for r in conn.execute(sa.select(raw_events.c.webhook_event_id)).all()}
    missing: list[Path] = []
    now = iso(datetime.now(UTC))
    for path in sorted(settings.paths.raw.rglob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        ev = parse_event(payload)
        if ev.webhook_event_id in known or ev.user_id not in settings.allowed_user_ids:
            continue
        missing.append(path)
        if dry_run:
            continue
        conn.execute(
            sa.insert(raw_events).values(
                webhook_event_id=ev.webhook_event_id,
                line_message_id=ev.message_id,
                user_id=ev.user_id,
                type=ev.type,
                message_type=ev.message_type,
                payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                is_redelivery=ev.is_redelivery,
                event_at=iso(from_ms(ev.timestamp_ms)),
                received_at=now,
            )
        )
    return missing


def main(argv: Sequence[str] | None = None, settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.reprocess")
    parser.add_argument("kind", choices=("lesson", "raw"))
    parser.add_argument("--since", help="この日付 (YYYY-MM-DD) 以降に取り込んだものだけ")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    settings = settings or Settings.from_env()
    if not settings.paths.db.exists():
        print(f"{settings.paths.db} がありません", file=sys.stderr)
        return 1
    engine = _engine(settings)
    try:
        with engine.begin() as conn:
            if args.kind == "lesson":
                changes = reprocess_lessons(conn, settings, args.since, args.dry_run)
                for c in changes:
                    if c.changed:
                        print(f"capture #{c.capture_id}: {c.before} → {c.after} 球 (status={c.status})")
                n = sum(c.changed for c in changes)
                print(f"lesson: {len(changes)} 件中 {n} 件が変わる (parser {PARSER_VERSION})" + (" [dry-run]" if args.dry_run else ""))
            else:
                missing = import_missing_raw(conn, settings, args.dry_run)
                for path in missing:
                    print(f"missing: {path.relative_to(settings.paths.root)}")
                print(f"raw: DB に無い原本 {len(missing)} 件" + (" [dry-run]" if args.dry_run else " を取り込みました"))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
