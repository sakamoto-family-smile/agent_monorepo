"""remediation のジョブ。

| ジョブ | 間隔 | 内容 |
|---|---|---|
| mirror | 10 分 | origin/main の写し (data/remediation/main) を最新のコミットにする |
| plan | 60 分 | 修正版のある Finding から、サービスごとに上げるパッケージを決めて updater に依頼する |
| collect | 5 分 | updater の結果を差分検査にかけ、通れば PR を作って自動マージを予約する |
| track | 10 分 | PR の CI・マージ・デプロイ・マージ後の照合を追う。トークンの期限も見る (tracker.py) |

1 つのサービスで同時に進める改修は 1 本まで (同じ uv.lock を書き換える PR が並ぶと、1 本マージした時点で
残りがぶつかるため)。まとめた PR の CI が落ちたら、そのサービスは 1 パッケージずつにする。
remediation.db にだけ書き、detection.db・intel.db は読み取り専用で開く。
"""
from __future__ import annotations

import json
import logging
import tomllib
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine, text

from ..common.services import Service, load_services
from ..common.timeutil import parse_iso, to_iso, utc_now
from ..detection.lockfiles import canonical_pypi_name
from . import guard
from .github import GitHub, GitHubError
from .jobs import InvalidJob, UpdateJob, new_run_id, read_result, remove_job, write_job
from .mirror import MainMirror
from .planner import Plan, plan_service, refine
from .store import EVENT_FAILED, EVENT_PR_OPENED, Run, Store
from .tracker import track

logger = logging.getLogger(__name__)

JOB_MIRROR = "mirror"
JOB_PLAN = "plan"
JOB_COLLECT = "collect"
JOB_TRACK = "track"
SERVICES_IN_REPO = "security-platform/config/services.yaml"
PR_TEXT = "依存の更新"  # PR のタイトル・本文・コミットに入れるのはこれだけ (どの脆弱性かは書かない)


@dataclass(frozen=True)
class RemediationSettings:
    min_priority: str = "P3"
    open_prs: bool = False  # False なら差分検査まで (PR は作らず dry_run で終わる)
    update_timeout: timedelta = timedelta(hours=2)
    token_warn_days: int = 30
    base_branch: str = "main"
    deploy_workflow: str = "deploy.yml"
    required_checks: tuple[str, ...] = ("CI result", "Secret scan (gitleaks)", "Python SAST (bandit)")


class RemediationPipeline:
    def __init__(
        self, engine: Engine, mirror: MainMirror, *, github: GitHub | None = None,
        detection: Callable[[], Engine | None] = lambda: None, intel: Callable[[], Engine | None] = lambda: None,
        jobs_dir: Path | None = None, events_dir: Path | None = None,
        cfg: RemediationSettings | None = None,
    ) -> None:
        self.engine = engine
        self.mirror = mirror
        self.github = github or mirror.github
        self._detection = detection  # 読み取り専用。まだ無ければ None
        self._intel = intel
        self.jobs_dir = jobs_dir or mirror.root / "jobs"
        self.store = Store(engine, events_dir or mirror.root / "events")
        self.cfg = cfg or RemediationSettings()

    @property
    def in_dir(self) -> Path:
        return self.jobs_dir / "in"

    @property
    def out_dir(self) -> Path:
        return self.jobs_dir / "out"

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

    # ── 計画 ──────────────────────────────────────────────────────────────
    def services(self, snapshot: Path) -> list[Service]:
        return load_services(snapshot / SERVICES_IN_REPO)

    def run_plan(self) -> None:
        with self._run(JOB_PLAN) as detail:
            sha = self.mirror.current()
            detection = self._detection()
            if sha is None or detection is None:
                detail["skipped"] = "写しがまだ無い" if sha is None else "detection.db がありません"
                return
            snapshot = self.mirror.snapshots / sha  # 計画の途中で写しが切り替わっても同じコミットを使う
            queued, skipped = [], {}
            for svc in self.services(snapshot):
                if not svc.auto_remediation or self.store.active(svc.id):
                    continue
                plan = plan_service(detection, svc, self.cfg.min_priority, self.store.attempted(svc.id))
                if plan is None:
                    continue
                plan = refine(plan, self._intel())
                if plan.skipped:
                    skipped[svc.id] = [f"{s.name} ({s.reason})" for s in plan.skipped]
                if plan.bumps and (run_id := self._queue(plan, sha, snapshot)):
                    queued.append(run_id)
            detail.update(sha=sha, queued=queued, skipped=skipped)

    def _queue(self, plan: Plan, sha: str, snapshot: Path) -> str | None:
        locked = _locked_versions(snapshot / plan.lockfile)
        # 照合が写しより古いと、もう上がっているものを下げてしまうので、写しの lockfile の版と突き合わせる
        attempted = self.store.attempted(plan.service.id)  # refine で上げた先の版も、前に失敗していれば見送る
        bumps = [b for b in plan.bumps if locked.get(b.name) == (b.current,) and (b.name, b.target) not in attempted]
        mode = self.store.mode(plan.service.id)
        bumps = bumps if mode == "bundle" else bumps[:1]
        if not bumps:
            return None
        run_id = new_run_id()
        project = plan.service.path.rstrip("/")
        write_job(self.in_dir, UpdateJob(run_id, project, tuple((b.name, b.target) for b in bumps)), snapshot)
        packages = [{"name": b.name, "current": b.current, "target": b.target, "priority": b.priority,
                     "finding_ids": list(b.finding_ids)} for b in bumps]
        with self.engine.begin() as conn:
            self.store.insert(conn, run_id=run_id, service_id=plan.service.id, lockfile=plan.lockfile, mode=mode,
                              manual=any(b.priority == "P1" for b in bumps), base_sha=sha, packages=packages,
                              detail={"skipped": [f"{s.name} ({s.reason})" for s in plan.skipped]})
        logger.info("queued %s: %s %s", run_id, plan.service.id, [f"{b.name}=={b.target}" for b in bumps])
        return run_id

    # ── 結果の回収と PR ───────────────────────────────────────────────────
    def run_collect(self) -> None:
        with self._run(JOB_COLLECT) as detail:
            counts: dict[str, int] = {}
            for run in self.store.runs(("queued",)):
                status = self._collect(run)
                if status:
                    counts[status] = counts.get(status, 0) + 1
            detail.update(counts)

    def _fail(self, run: Run, status: str, stage: str, reason: str, *,
              attempts: Sequence[tuple[str, str, str]] = (), detail: dict[str, object] | None = None) -> str:
        outbox = self.store.outbox()
        with self.engine.begin() as conn:
            run = self.store.update(conn, run, status, detail={"stage": stage, "reason": reason, **(detail or {})})
            if attempts:
                self.store.add_attempts(conn, run.service_id, run.run_id, list(attempts))
            outbox.publish(conn, EVENT_FAILED, {**run.summary(), "stage": stage, "reason": reason[:1000]})
        outbox.flush()
        logger.warning("%s %s: %s", run.run_id, status, reason[:300])
        return status

    def _collect(self, run: Run) -> str | None:
        try:
            result = read_result(self.out_dir, run.run_id)
        except InvalidJob as e:
            remove_job(self.in_dir, self.out_dir, run.run_id)
            return self._fail(run, "error", "update", f"updater の結果を読めない: {e}")
        if result is None:
            if utc_now() - parse_iso(run.created_at) > self.cfg.update_timeout:
                remove_job(self.in_dir, self.out_dir, run.run_id)
                return self._fail(run, "error", "update", "updater が応答しない (remediation-updater が止まっている?)")
            return None
        targets = {p["name"]: p["target"] for p in run.packages}
        failed = [(name, targets.get(name, "?"), out) for name, out in result.failed]
        try:
            if not result.ok or result.lock is None:
                reason = result.error or "; ".join(f"{n}: {_last_line(o)}" for n, _, o in failed) or "uv lock failed"
                return self._fail(run, "update_failed", "update", reason,
                                  attempts=[(n, t, _last_line(o)) for n, t, o in failed])
            old_lock = (self.in_dir / run.run_id / "tree" / run.lockfile).read_text(encoding="utf-8")
            applied = [p for p in run.packages if p["name"] in result.applied]
            g = guard.check(old_lock, result.lock, {p["name"]: p["target"] for p in applied}, intel=self._intel())
            changes = [f"{c.name} {','.join(c.old) or '-'} → {','.join(c.new) or '-'}" for c in g.changes]
            if not g.ok:
                return self._fail(run, "guard_failed", "guard", "; ".join(g.problems[:10]),
                                  attempts=[(p["name"], p["target"], "guard") for p in applied],
                                  detail={"changes": changes})
            extra = {"changes": changes, "residual": g.residual, "not_applied": [n for n, _, _ in failed],
                     "uv_version": result.uv_version}
            with self.engine.begin() as conn:
                if failed:
                    self.store.add_attempts(conn, run.service_id, run.run_id,
                                            [(n, t, _last_line(o)) for n, t, o in failed])
                run = self.store.update(conn, run, detail=extra, packages=applied)
            if not self.cfg.open_prs or not self.github.token:
                with self.engine.begin() as conn:
                    self.store.update(conn, run, "dry_run")
                return "dry_run"
            return self._open_pr(run, result.lock)
        finally:
            remove_job(self.in_dir, self.out_dir, run.run_id)

    def _open_pr(self, run: Run, lock: str) -> str:
        branch = f"remediation/{run.service_id}-{run.run_id.removeprefix('rem_')[:8]}"
        title = f"chore({run.service_id}): {PR_TEXT}"
        created = False
        try:
            commit = self.github.create_commit(run.base_sha, run.lockfile, lock, title)
            self.github.create_branch(branch, commit)
            created = True
            files = self.github.changed_files(run.base_sha, commit)
            if files != [run.lockfile]:  # lockfile 以外は絶対に変えない
                raise GitHubError(f"unexpected files in the commit: {files[:5]}")
            pr = self.github.create_pull(branch, self.cfg.base_branch, title, PR_TEXT)
            auto = not run.manual
            if auto:
                self.github.enable_auto_merge(str(pr["node_id"]))
        except GitHubError as e:
            if created:
                try:
                    self.github.delete_branch(branch)
                except GitHubError:
                    logger.warning("could not delete %s", branch, exc_info=True)
            return self._fail(run, "error", "pr", str(e))
        outbox = self.store.outbox()
        with self.engine.begin() as conn:
            run = self.store.update(conn, run, "pr_open", branch=branch, pr_number=int(pr["number"]),
                                    pr_url=str(pr["html_url"]), head_sha=commit, detail={"auto_merge": auto})
            outbox.publish(conn, EVENT_PR_OPENED, {**run.summary(), "auto_merge": auto})
        outbox.flush()
        logger.info("%s: opened %s (auto-merge=%s)", run.run_id, run.pr_url, auto)
        return "pr_open"


    # ── 追跡 ──────────────────────────────────────────────────────────────
    def run_track(self) -> None:
        with self._run(JOB_TRACK) as detail:
            detail.update(track(self))


def _last_line(output: str) -> str:
    lines = [ln.strip() for ln in output.strip().splitlines() if ln.strip()]
    return lines[-1][:300] if lines else ""


def _locked_versions(path: Path) -> dict[str, tuple[str, ...]]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    out: dict[str, list[str]] = {}
    for p in data.get("package") or []:
        if "name" in p and "version" in p:
            out.setdefault(canonical_pypi_name(p["name"]), []).append(str(p["version"]))
    return {k: tuple(sorted(v)) for k, v in out.items()}
