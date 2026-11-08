"""remediation.db の改修の記録 (runs・run_steps・attempts・service_modes・state) とイベント。

イベント (remediation.db の events + data/events/*.jsonl) は notify が読み取り専用で読んで LINE に送る:

| type | いつ | notify |
|---|---|---|
| remediation.pr_opened | PR を作った | 人がマージするもの (P1) だけすぐ送る。他は日次まとめ |
| remediation.failed | 更新・差分検査・CI で止まった | すぐ送る |
| remediation.merged | マージされた | 日次まとめ |
| remediation.not_resolved | マージ後の照合でも lockfile の Finding が閉じない | すぐ送る |
| remediation.deployed / deploy_failed | 自動デプロイの結果 | 失敗だけすぐ送る |
| remediation.token_expiring | GitHub のトークンの期限が近い | すぐ送る |

payload にはパッケージ名と版が入る (LINE とローカルの DB にだけ残り、リポジトリには出ない)。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, text

from ..common.events import Outbox
from ..common.timeutil import to_iso, utc_now

ACTIVE = ("queued", "pr_open", "merged")  # この間は同じサービスで次の改修を始めない
TERMINAL = ("verified", "not_resolved", "update_failed", "guard_failed", "ci_failed", "conflict", "closed",
            "dry_run", "error")

EVENT_PR_OPENED = "remediation.pr_opened"
EVENT_FAILED = "remediation.failed"
EVENT_MERGED = "remediation.merged"
EVENT_NOT_RESOLVED = "remediation.not_resolved"
EVENT_DEPLOYED = "remediation.deployed"
EVENT_DEPLOY_FAILED = "remediation.deploy_failed"
EVENT_TOKEN_EXPIRING = "remediation.token_expiring"

COLUMNS = ("run_id", "service_id", "lockfile", "status", "mode", "manual", "base_sha", "branch", "pr_number",
           "pr_url", "head_sha", "merge_sha", "deploy_status", "packages_json", "detail_json", "created_at",
           "updated_at", "finished_at")


@dataclass(frozen=True)
class Run:
    run_id: str
    service_id: str
    lockfile: str
    status: str
    mode: str
    manual: bool
    base_sha: str
    branch: str | None
    pr_number: int | None
    pr_url: str | None
    head_sha: str | None
    merge_sha: str | None
    deploy_status: str | None
    packages: list[dict[str, Any]]
    detail: dict[str, Any]
    created_at: str
    updated_at: str
    finished_at: str | None

    @classmethod
    def from_row(cls, row: Any) -> Run:
        d = dict(zip(COLUMNS, row, strict=True))
        packages = json.loads(d.pop("packages_json"))
        detail = json.loads(d.pop("detail_json") or "{}")
        return cls(**{**d, "manual": bool(d["manual"]), "packages": packages, "detail": detail})

    def summary(self) -> dict[str, Any]:
        """イベントの payload に入れる共通の項目。"""
        return {
            "run_id": self.run_id, "service_id": self.service_id, "pr_url": self.pr_url, "manual": self.manual,
            "packages": [{"name": p["name"], "current": p["current"], "target": p["target"]}
                         for p in self.packages],
        }


class Store:
    def __init__(self, engine: Engine, events_dir: Path) -> None:
        self.engine = engine
        self.events_dir = events_dir

    # ── runs ──────────────────────────────────────────────────────────────
    def get(self, run_id: str) -> Run:
        with self.engine.connect() as conn:
            row = conn.execute(text(f"SELECT {', '.join(COLUMNS)} FROM runs WHERE run_id = :r"),  # nosec B608
                               {"r": run_id}).one()
        return Run.from_row(row)

    def runs(self, statuses: tuple[str, ...] | None = None, service_id: str | None = None) -> list[Run]:
        sql = f"SELECT {', '.join(COLUMNS)} FROM runs WHERE 1 = 1"  # nosec B608  列名は定数
        params: dict[str, Any] = {}
        if statuses:
            sql += " AND status IN (" + ", ".join(f":s{i}" for i in range(len(statuses))) + ")"
            params.update({f"s{i}": s for i, s in enumerate(statuses)})
        if service_id:
            sql += " AND service_id = :svc"
            params["svc"] = service_id
        with self.engine.connect() as conn:
            rows = conn.execute(text(sql + " ORDER BY created_at"), params).all()
        return [Run.from_row(r) for r in rows]

    def active(self, service_id: str) -> Run | None:
        runs = self.runs(ACTIVE, service_id)
        return runs[0] if runs else None

    def insert(self, conn: Connection, *, run_id: str, service_id: str, lockfile: str, mode: str, manual: bool,
               base_sha: str, packages: list[dict[str, Any]], detail: dict[str, Any]) -> None:
        now = to_iso(utc_now())
        conn.execute(text(
            "INSERT INTO runs (run_id, service_id, lockfile, status, mode, manual, base_sha, packages_json, "
            "detail_json, created_at, updated_at) VALUES (:r, :s, :l, 'queued', :m, :manual, :b, :p, :d, :t, :t)"
        ), {"r": run_id, "s": service_id, "l": lockfile, "m": mode, "manual": manual, "b": base_sha,
            "p": json.dumps(packages, ensure_ascii=False), "d": json.dumps(detail, ensure_ascii=False), "t": now})
        self.step(conn, run_id, "plan", "queued", {"packages": [p["name"] for p in packages], **detail})

    def update(self, conn: Connection, run: Run, status: str | None = None, *,
               detail: dict[str, Any] | None = None, packages: list[dict[str, Any]] | None = None,
               **fields: Any) -> Run:
        """status・detail (前のものに足す)・列を書き換えて、書き換えた後の Run を返す。"""
        now = to_iso(utc_now())
        values: dict[str, Any] = {"updated_at": now, **fields}
        if status is not None:
            values["status"] = status
            if status in TERMINAL:
                values["finished_at"] = now
        if detail is not None:
            values["detail_json"] = json.dumps({**run.detail, **detail}, ensure_ascii=False)
        if packages is not None:
            values["packages_json"] = json.dumps(packages, ensure_ascii=False)
        sets = ", ".join(f"{k} = :{k}" for k in values)
        conn.execute(text(f"UPDATE runs SET {sets} WHERE run_id = :run_id"),  # nosec B608  列名はこのモジュールが決める
                     {**values, "run_id": run.run_id})
        if status is not None and status != run.status:
            self.step(conn, run.run_id, status, "done", detail or {})
        return self.get_in(conn, run.run_id)

    def get_in(self, conn: Connection, run_id: str) -> Run:
        row = conn.execute(text(f"SELECT {', '.join(COLUMNS)} FROM runs WHERE run_id = :r"),  # nosec B608
                           {"r": run_id}).one()
        return Run.from_row(row)

    @staticmethod
    def step(conn: Connection, run_id: str, step: str, status: str, detail: dict[str, Any]) -> None:
        now = to_iso(utc_now())
        conn.execute(text(
            "INSERT INTO run_steps (run_id, step, status, detail_json, started_at, finished_at) "
            "VALUES (:r, :s, :st, :d, :t, :t)"
        ), {"r": run_id, "s": step, "st": status, "d": json.dumps(detail, ensure_ascii=False)[:20_000], "t": now})

    # ── 試した版・まとめ方 ────────────────────────────────────────────────
    def attempted(self, service_id: str) -> set[tuple[str, str]]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("SELECT package, target FROM attempts WHERE service_id = :s"),
                                {"s": service_id}).all()
        return {(r[0], r[1]) for r in rows}

    @staticmethod
    def add_attempts(conn: Connection, service_id: str, run_id: str, items: list[tuple[str, str, str]]) -> None:
        for package, target, reason in items:
            conn.execute(text(
                "INSERT OR REPLACE INTO attempts (service_id, package, target, reason, run_id, created_at) "
                "VALUES (:s, :p, :t, :r, :run, :now)"
            ), {"s": service_id, "p": package, "t": target, "r": reason[:500], "run": run_id,
                "now": to_iso(utc_now())})

    def mode(self, service_id: str) -> str:
        with self.engine.connect() as conn:
            v = conn.execute(text("SELECT mode FROM service_modes WHERE service_id = :s"), {"s": service_id}).scalar()
        return str(v) if v else "bundle"

    @staticmethod
    def set_mode(conn: Connection, service_id: str, mode: str, reason: str) -> None:
        conn.execute(text(
            "INSERT INTO service_modes (service_id, mode, reason, updated_at) VALUES (:s, :m, :r, :t) "
            "ON CONFLICT(service_id) DO UPDATE SET mode = excluded.mode, reason = excluded.reason, "
            "updated_at = excluded.updated_at"
        ), {"s": service_id, "m": mode, "r": reason, "t": to_iso(utc_now())})

    def get_state(self, key: str) -> str | None:
        with self.engine.connect() as conn:
            v = conn.execute(text("SELECT value FROM state WHERE key = :k"), {"k": key}).scalar()
        return str(v) if v is not None else None

    @staticmethod
    def set_state(conn: Connection, key: str, value: str) -> None:
        conn.execute(text(
            "INSERT INTO state (key, value, updated_at) VALUES (:k, :v, :t) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at"
        ), {"k": key, "v": value, "t": to_iso(utc_now())})

    # ── イベント ──────────────────────────────────────────────────────────
    def outbox(self) -> Outbox:
        return Outbox(self.events_dir, "remediation")
