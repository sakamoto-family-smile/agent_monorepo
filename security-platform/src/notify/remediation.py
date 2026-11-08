"""自動改修 (remediation) の通知の文面。remediation.db は読み取り専用で開く。

すぐ送るもの: 止まった (更新・差分検査・CI・PR の作成)、人がマージする PR (P1)、マージ後も lockfile の
Finding が閉じない、自動デプロイの失敗、GitHub のトークンの期限。それ以外 (PR の作成・マージ・デプロイ) は
日次まとめに件数で載せる。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError

from ..common.events import Event
from ..common.timeutil import to_iso

IMMEDIATE = ("remediation.failed", "remediation.pr_opened", "remediation.not_resolved",
             "remediation.deploy_failed", "remediation.token_expiring")
STAGE_LABELS = {"update": "依存の更新 (uv lock) で", "guard": "差分検査で", "ci": "CI で", "pr": "PR の作成で"}
STATUS_LABELS = {"queued": "更新中", "pr_open": "CI 待ち", "merged": "マージ済み (照合待ち)",
                 "landed": "マージ済み (照合待ち)"}
LIST_LIMIT = 10


def _packages(p: dict[str, Any]) -> list[str]:
    return [f"・{x['name']} {x['current']} → {x['target']}" for x in p.get("packages") or []][:LIST_LIMIT]


def alert(event: Event) -> str | None:
    """すぐ送る文面。送らないイベントなら None。"""
    p = event.payload
    svc = p.get("service_id", "?")
    pr = [f"PR: {p['pr_url']}"] if p.get("pr_url") else []
    if event.type == "remediation.failed":
        stage = STAGE_LABELS.get(str(p.get("stage")), f"{p.get('stage')} で")
        return "\n".join([f"【自動改修】{svc}: {stage}止まりました", *_packages(p),
                          f"理由: {str(p.get('reason') or '')[:600]}", *pr])
    if event.type == "remediation.pr_opened":
        if p.get("auto_merge", True):
            return None
        return "\n".join([f"【自動改修】{svc}: P1 (悪性・悪用確認済み) の修正 PR を作りました。確認してマージしてください",
                          *_packages(p), *pr])
    if event.type == "remediation.not_resolved":
        head = f"【自動改修】{svc}: マージしましたが、lockfile の Finding が閉じていません ({p.get('remaining', '?')} 件)"
        return "\n".join([head, *_packages(p), *pr])
    if event.type == "remediation.deploy_failed":
        url = [f"デプロイ: {p['workflow_url']}"] if p.get("workflow_url") else []
        return "\n".join([f"【自動改修】{svc}: 自動デプロイが失敗しました (本番は前の版のまま)", *url, *pr])
    if event.type == "remediation.token_expiring":
        expires = str(p.get("expires_at", ""))[:10]
        return (f"【自動改修】GitHub のトークンの期限まで残り {p.get('days_left')} 日です ({expires})。"
                "作り直して config/remediation.env を更新してください (権限は前と同じ)")
    return None


def digest_section(engine: Engine | None, since: datetime) -> list[str]:
    """日次まとめの「自動改修」の段。remediation.db が無い・まだ何もしていなければ空。"""
    if engine is None:
        return []
    try:
        with engine.connect() as conn:
            counts = dict(conn.execute(text(
                "SELECT type, count(*) FROM events WHERE occurred_at > :s GROUP BY type"), {"s": to_iso(since)}).all())
            active = conn.execute(text(
                "SELECT service_id, status, pr_url FROM runs WHERE status IN ('queued', 'pr_open', 'merged', "
                "'landed') ORDER BY created_at")).all()
            waiting = conn.execute(text(
                "SELECT DISTINCT service_id FROM runs WHERE deploy_status = 'success' AND status = 'verified' "
                "AND CAST(json_extract(detail_json, '$.waiting_image') AS INTEGER) > 0 AND updated_at > :s"),
                {"s": to_iso(since)}).all()
    except OperationalError:  # まだスキーマが古い
        return []
    n = {k.removeprefix("remediation."): v for k, v in counts.items()}
    if not (n or active):
        return []
    stopped = n.get("failed", 0) + n.get("deploy_failed", 0)
    head = (f"■ 自動改修 (前回から): PR {n.get('pr_opened', 0)} / マージ {n.get('merged', 0)} / "
            f"デプロイ {n.get('deployed', 0)} / 止まった {stopped}")
    lines = [head]
    lines += [f"・{svc}: {STATUS_LABELS.get(st, st)}{f' {url}' if url and st == 'pr_open' else ''}"
              for svc, st, url in active[:LIST_LIMIT]]
    if waiting:
        lines.append("・デプロイ済み・本番イメージの SBOM の更新待ち: " + ", ".join(r[0] for r in waiting)
                     + " (make detection-images)")
    return lines
