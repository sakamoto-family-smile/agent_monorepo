"""PR を作った後の追跡 (track ジョブ)。

    pr_open ──マージ──▶ merged ──写しに入る──▶ landed ──照合で Finding が閉じる──▶ verified
       │                                          └──閉じない──▶ not_resolved (すぐ通知)
       ├─ CI が落ちた ──▶ ci_failed (PR を閉じる。まとめた PR なら次から 1 つずつ。すぐ通知)
       ├─ main とぶつかった ──▶ conflict (PR を閉じる。次の計画で今の main から作り直す)
       └─ 人が閉じた ──▶ closed

本番イメージにも同じ版が入っているサービスでは、lockfile を直しても Finding は本番イメージの側で
開いたまま残る (デプロイして make detection-images で SBOM を作り直すと閉じる)。
それは「直っていない」ではないので、lockfile の側で残っているときだけ not_resolved にする。
デプロイ (main へのマージで deploy.yml) の結果も追い、失敗したら知らせる。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import Engine, text

from ..common.timeutil import parse_iso, to_iso, utc_now
from .github import GitHubError
from .store import (
    EVENT_DEPLOY_FAILED,
    EVENT_DEPLOYED,
    EVENT_FAILED,
    EVENT_MERGED,
    EVENT_NOT_RESOLVED,
    EVENT_TOKEN_EXPIRING,
    Run,
)

if TYPE_CHECKING:
    from .pipeline import RemediationPipeline

logger = logging.getLogger(__name__)

FAILED_CONCLUSIONS = ("failure", "cancelled", "timed_out", "action_required", "startup_failure")
DEPLOY_WAIT = timedelta(hours=2)  # これを過ぎてもデプロイの run が無ければ、デプロイ対象外とみなす
TOKEN_THRESHOLDS = (30, 14, 7, 3, 1)  # 残り日数がこれを切るたびに 1 回知らせる


def track(p: RemediationPipeline, now: datetime | None = None) -> dict[str, int]:
    now = now or utc_now()
    counts: dict[str, int] = {}

    def count(status: str | None) -> None:
        if status:
            counts[status] = counts.get(status, 0) + 1

    for run in p.store.runs(("pr_open",)):
        count(_track_pr(p, run))
    for run in p.store.runs(("merged",)):
        count(_track_merged(p, run, now))
    detection = p._detection()
    for run in p.store.runs(("landed",)):
        count(_verify(p, run, detection))
    for run in p.store.runs(("merged", "landed", "verified", "not_resolved")):
        if run.deploy_status in (None, "pending"):
            count(_track_deploy(p, run, now))
    _check_token(p, now)
    return counts


def _publish(p: RemediationPipeline, run: Run, status: str | None, event: str | None, payload: dict | None = None,
             **fields: object) -> Run:
    outbox = p.store.outbox()
    with p.engine.begin() as conn:
        run = p.store.update(conn, run, status, **fields)  # type: ignore[arg-type]
        if event:
            outbox.publish(conn, event, {**run.summary(), **(payload or {})})
    outbox.flush()
    return run


# ── PR ────────────────────────────────────────────────────────────────────
def _track_pr(p: RemediationPipeline, run: Run) -> str | None:
    assert run.pr_number is not None
    pr = p.github.get_pull(run.pr_number)
    if pr.get("merged"):
        _publish(p, run, "merged", EVENT_MERGED, merge_sha=str(pr["merge_commit_sha"]),
                 detail={"merged_at": pr.get("merged_at")})
        return "merged"
    if pr.get("state") == "closed":
        _publish(p, run, "closed", None, detail={"reason": "PR が閉じられた"})
        return "closed"
    failed = _failed_checks(p, str(pr["head"]["sha"]))
    if failed:
        _close(p, run)
        reason = "CI が落ちた: " + ", ".join(failed)
        outbox = p.store.outbox()
        with p.engine.begin() as conn:
            if run.mode == "bundle" and len(run.packages) > 1:
                p.store.set_mode(conn, run.service_id, "single", f"{run.run_id}: {reason}")
            else:  # 1 つだけでも落ちるなら、この版では二度と試さない
                p.store.add_attempts(conn, run.service_id, run.run_id,
                                     [(x["name"], x["target"], "ci") for x in run.packages])
            run = p.store.update(conn, run, "ci_failed", detail={"stage": "ci", "reason": reason})
            outbox.publish(conn, EVENT_FAILED, {**run.summary(), "stage": "ci", "reason": reason})
        outbox.flush()
        return "ci_failed"
    if pr.get("mergeable_state") == "dirty":  # main とぶつかった。次の計画で今の main から作り直す
        _close(p, run)
        _publish(p, run, "conflict", None, detail={"reason": "main とぶつかった"})
        return "conflict"
    return None


def _failed_checks(p: RemediationPipeline, sha: str) -> list[str]:
    runs = p.github.check_runs(sha)
    return sorted({str(c["name"]) for c in runs
                   if c.get("name") in p.cfg.required_checks and c.get("conclusion") in FAILED_CONCLUSIONS})


def _close(p: RemediationPipeline, run: Run) -> None:
    assert run.pr_number is not None
    p.github.close_pull(run.pr_number)
    if run.branch:
        try:
            p.github.delete_branch(run.branch)
        except GitHubError:
            logger.warning("could not delete %s", run.branch, exc_info=True)


# ── マージの後 ────────────────────────────────────────────────────────────
def _track_merged(p: RemediationPipeline, run: Run, now: datetime) -> str | None:
    """写しがマージを含んだら landed (次の照合でこの lockfile が読まれる)。"""
    sha = p.mirror.current()
    if sha is None or run.merge_sha is None:
        return None
    if sha != run.merge_sha and p.github.compare_status(run.merge_sha, sha) not in ("ahead", "identical"):
        return None
    _publish(p, run, "landed", None, detail={"landed_at": to_iso(now), "landed_sha": sha})
    return "landed"


def _verify(p: RemediationPipeline, run: Run, detection: Engine | None) -> str | None:
    """landed の後に照合が 1 回終わっていたら、対象の Finding が lockfile の側で閉じたかを見る。"""
    if detection is None:
        return None
    landed_at = parse_iso(run.detail["landed_at"])
    with detection.connect() as conn:
        last = conn.execute(text(
            "SELECT MAX(finished_at) FROM scan_runs WHERE job = 'scan' AND status = 'success'")).scalar()
        if last is None or parse_iso(last) <= landed_at:
            return None
        ids = [f for x in run.packages for f in x["finding_ids"]]
        rows = conn.execute(text(
            "SELECT finding_id, state, evidence_json FROM findings WHERE finding_id IN ("
            + ", ".join(f":f{i}" for i in range(len(ids))) + ")"), {f"f{i}": v for i, v in enumerate(ids)}).all()
    remaining = [r[0] for r in rows if r[1] == "open" and json.loads(r[2]).get("source_kind") == "source"]
    image = [r[0] for r in rows if r[1] == "open" and json.loads(r[2]).get("source_kind") != "source"]
    detail = {"verified_scan_at": last, "waiting_image": len(image)}
    if remaining:
        _publish(p, run, "not_resolved", EVENT_NOT_RESOLVED, {"remaining": len(remaining)},
                 detail={**detail, "remaining": remaining})
        return "not_resolved"
    _publish(p, run, "verified", None, detail=detail)
    return "verified"


def _track_deploy(p: RemediationPipeline, run: Run, now: datetime) -> str | None:
    """deploy.yml の結果。対象外のサービスや、デプロイの仕組みがまだ無ければ none。"""
    if run.merge_sha is None:
        return None
    try:
        runs = p.github.workflow_runs(p.cfg.deploy_workflow, run.merge_sha)
    except GitHubError:  # ワークフローが無い (404) など
        runs = []
    merged_at = parse_iso(str(run.detail.get("merged_at") or run.updated_at))
    if not runs:
        if now - merged_at > DEPLOY_WAIT:
            _publish(p, run, None, None, deploy_status="none")
            return "deploy_none"
        return None
    wf = max(runs, key=lambda r: str(r.get("created_at", "")))
    if wf.get("status") != "completed":
        if run.deploy_status != "pending":
            _publish(p, run, None, None, deploy_status="pending")
        return None
    job = next((j for j in p.github.run_jobs(int(wf["id"])) if j.get("name") == f"Deploy / {run.service_id}"), None)
    if job is None or job.get("conclusion") == "skipped":
        _publish(p, run, None, None, deploy_status="none")
        return "deploy_none"
    if job.get("conclusion") == "success":
        _publish(p, run, None, EVENT_DEPLOYED, deploy_status="success")
        return "deployed"
    _publish(p, run, None, EVENT_DEPLOY_FAILED, {"workflow_url": wf.get("html_url")}, deploy_status="failed",
             detail={"deploy_url": wf.get("html_url")})
    return "deploy_failed"


# ── トークンの期限 ────────────────────────────────────────────────────────
def _check_token(p: RemediationPipeline, now: datetime) -> None:
    expires = p.github.token_expires_at
    if expires is None:
        return
    days = (expires - now).days
    crossed = [t for t in TOKEN_THRESHOLDS if days < t]
    if not crossed or days >= p.cfg.token_warn_days:
        return
    threshold = min(crossed)
    key = f"token_notice:{expires.date().isoformat()}"
    last = p.store.get_state(key)
    if last is not None and int(last) <= threshold:
        return
    outbox = p.store.outbox()
    with p.engine.begin() as conn:
        p.store.set_state(conn, key, str(threshold))
        outbox.publish(conn, EVENT_TOKEN_EXPIRING, {"expires_at": to_iso(expires), "days_left": days})
    outbox.flush()
