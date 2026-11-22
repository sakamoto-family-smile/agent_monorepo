"""fetch_media: LINE から動画・画像を取得して data/media/YYYY/MM/<sha256>.<ext> に保存する。

LINE のコンテンツは保存期間が限られるので、受け付けたらすぐジョブに積む。
動画は変換が終わるまで取得できないので、変換の状態を見てから取得する。
"""
from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path

import sqlalchemy as sa

from app.deps import Deps
from app.jobs.queue import Job
from app.jobs.worker import JobKind, PermanentError, PollLater
from app.line.api import LineApiError
from app.push import push_text
from app.storage.tables import media, raw_events
from app.timeutil import parse_iso

KIND = "fetch_media"
TRANSCODING_POLL = timedelta(seconds=10)
# 変換待ちは 15 分まで (10 秒 × 90 回)。超えたら失敗を 1 回数えて、バックオフで続ける
MAX_TRANSCODING_POLLS = 90
# 404 / 410: LINE 側でコンテンツが消えた (保存期間切れ)。再試行しても取れない
GONE_STATUSES = frozenset({404, 410})
EXTENSIONS = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/heic": ".heic",
    "image/webp": ".webp",
}


async def run(deps: Deps, job: Job) -> None:
    async with deps.engine.connect() as conn:
        row = (
            await conn.execute(
                sa.select(media, raw_events.c.line_message_id, raw_events.c.payload_json)
                .join(raw_events, raw_events.c.id == media.c.raw_event_id)
                .where(media.c.id == job.ref_id)
            )
        ).first()
    if row is None:
        raise PermanentError("media not found")
    if row.status == "saved":
        return
    provider = (json.loads(row.payload_json).get("message") or {}).get("contentProvider") or {}
    if provider.get("type") == "external":
        raise PermanentError("external content (LINE に原本がない)")
    message_id = row.line_message_id

    if row.kind == "video":
        try:
            status = await deps.line.transcoding_status(message_id)
        except LineApiError as e:
            if e.status in GONE_STATUSES:
                raise PermanentError(str(e)) from e
            raise
        if status == "failed":
            raise PermanentError("transcoding failed")
        if status != "succeeded":
            if job.polls < MAX_TRANSCODING_POLLS:
                raise PollLater(TRANSCODING_POLL)
            raise TimeoutError("transcoding not finished")

    paths = deps.settings.paths
    paths.tmp.mkdir(parents=True, exist_ok=True)
    tmp = paths.tmp / f"media-{job.ref_id}.part"
    try:
        try:
            dl = await deps.line.download(message_id, tmp)
        except LineApiError as e:
            if e.status in GONE_STATUSES:
                raise PermanentError(str(e)) from e
            raise
        digest = dl.sha256
        ext = EXTENSIONS.get(dl.content_type, ".mp4" if row.kind == "video" else ".bin")
        local = parse_iso(row.created_at).astimezone(deps.settings.tz)
        rel = Path("media") / f"{local:%Y}" / f"{local:%m}" / f"{digest}{ext}"
        dest = paths.root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            tmp.unlink()
        else:
            os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)

    async with deps.engine.begin() as conn:
        await conn.execute(
            sa.update(media)
            .where(media.c.id == job.ref_id)
            .values(
                status="saved",
                path=rel.as_posix(),
                sha256=digest,
                size_bytes=dl.size_bytes,
                content_type=dl.content_type,
            )
        )


async def on_failed(deps: Deps, job: Job, error: str) -> None:
    async with deps.engine.begin() as conn:
        await conn.execute(sa.update(media).where(media.c.id == job.ref_id).values(status="failed"))
        row = (
            await conn.execute(
                sa.select(media.c.kind, raw_events.c.user_id)
                .join(raw_events, raw_events.c.id == media.c.raw_event_id)
                .where(media.c.id == job.ref_id)
            )
        ).first()
    if row is None:
        return
    label = "動画" if row.kind == "video" else "画像"
    await push_text(
        deps,
        to=row.user_id,
        kind="failure",
        key=f"fetch_media-failed-{job.ref_id}",
        body=f"⚠️ {label}を LINE から取得できませんでした（#{job.ref_id}）。原本のイベントは残っています。"
        f"もう一度送ってください。\n理由: {error[:100]}",
    )


JOB = JobKind(run=run, on_failed=on_failed)
