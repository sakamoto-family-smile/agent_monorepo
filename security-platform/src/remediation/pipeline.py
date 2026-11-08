"""remediation のジョブ。

| ジョブ | 間隔 | 内容 |
|---|---|---|
| mirror | 10 分 | origin/main の写し (data/remediation/main) を最新のコミットにする |

remediation.db にだけ書く。実行記録 (job_runs) の detail に写しのコミットを残す
(notify はそれを読み取り専用で見て、写しの更新が止まっていたら知らせる)。
"""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import Engine, text

from ..common.timeutil import parse_iso, to_iso, utc_now
from .mirror import MainMirror

logger = logging.getLogger(__name__)

JOB_MIRROR = "mirror"


class RemediationPipeline:
    def __init__(self, engine: Engine, mirror: MainMirror) -> None:
        self.engine = engine
        self.mirror = mirror

    # ── 実行記録 ──────────────────────────────────────────────────────────
    @contextmanager
    def _run(self, job: str) -> Iterator[dict[str, object]]:
        run_id = f"run_{uuid.uuid4().hex[:16]}"
        detail: dict[str, object] = {}
        with self.engine.begin() as conn:
            conn.execute(text("INSERT INTO job_runs (run_id, job, started_at, status) VALUES (:r, :j, :t, 'running')"),
                         {"r": run_id, "j": job, "t": to_iso(utc_now())})
        try:
            yield detail
        except Exception as e:
            self._finish(run_id, "failed", detail, f"{type(e).__name__}: {e}"[:2000])
            raise
        self._finish(run_id, "success", detail, None)

    def _finish(self, run_id: str, status: str, detail: dict[str, object], error: str | None) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE job_runs SET finished_at = :t, status = :s, detail = :d, error = :e "
                              "WHERE run_id = :r"),
                         {"t": to_iso(utc_now()), "s": status, "d": json.dumps(detail, ensure_ascii=False),
                          "e": error, "r": run_id})

    def last_success(self, job: str) -> datetime | None:
        with self.engine.connect() as conn:
            v = conn.execute(text("SELECT MAX(finished_at) FROM job_runs WHERE job = :j AND status = 'success'"),
                             {"j": job}).scalar()
        return parse_iso(v) if v else None

    # ── origin/main の写し ────────────────────────────────────────────────
    def run_mirror(self) -> None:
        with self._run(JOB_MIRROR) as detail:
            r = self.mirror.sync()
            detail.update(sha=r.sha, changed=r.changed, previous=r.previous)
