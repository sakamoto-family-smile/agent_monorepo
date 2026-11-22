"""redispatch: 原本は保存できたが、メモ・動画などへの保存が終わらなかったイベントをやり直す。

webhook は原本を保存するトランザクションでこのジョブを (少し先の時刻で) 積み、処理が終わったら消す。
処理が例外で失敗したとき・途中でプロセスが止まったときだけ残り、ワーカーがやり直す
(LINE には 200 を返しているので再送は来ない。原本から作り直すのはここだけ)。
make reprocess KIND=raw で DB に戻した原本もこのジョブで処理する。
結果は reply トークンが使えないので push で返す。
"""
from __future__ import annotations

import json
from datetime import timedelta

import sqlalchemy as sa

from app.deps import Deps
from app.handlers import dispatch
from app.jobs.queue import Job
from app.jobs.worker import JobKind, PermanentError
from app.line.events import LineEvent, parse_event
from app.push import push_text
from app.storage.tables import raw_events

KIND = "redispatch"
# webhook の処理が終わるまでの猶予 (この間に終われば消す)
GRACE = timedelta(minutes=2)


async def _event(deps: Deps, raw_id: int) -> tuple[LineEvent, str]:
    async with deps.engine.connect() as conn:
        row = (await conn.execute(sa.select(raw_events).where(raw_events.c.id == raw_id))).first()
    if row is None:
        raise PermanentError("raw event not found")
    return parse_event(json.loads(row.payload_json)), row.user_id


async def run(deps: Deps, job: Job) -> None:
    ev, user_id = await _event(deps, job.ref_id)
    now = deps.clock()
    async with deps.engine.begin() as conn:
        messages = await dispatch.handle(
            dispatch.Context(deps=deps, conn=conn, ev=ev, raw_event_id=job.ref_id, now=now)
        )
    texts = [m["text"] for m in messages if m.get("type") == "text"]
    if texts:
        await push_text(
            deps, to=user_id, kind="redispatch", key=f"redispatch-{job.ref_id}", body=f"（やり直して保存しました）\n{texts[0]}"
        )


async def on_failed(deps: Deps, job: Job, error: str) -> None:
    _, user_id = await _event(deps, job.ref_id)
    await push_text(
        deps,
        to=user_id,
        kind="failure",
        key=f"redispatch-failed-{job.ref_id}",
        body=f"⚠️ 送ったもの（#{job.ref_id}）を保存できませんでした。原本は残っています。\n理由: {error[:100]}",
    )


JOB = JobKind(run=run, on_failed=on_failed)
