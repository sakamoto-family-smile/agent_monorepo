"""B 自動改修 (remediation サービス) の CLI。

    python -m src.remediation serve     # docker compose 用の常駐 (写し・計画・回収と PR・追跡)
    python -m src.remediation mirror    # origin/main の写し (data/remediation/main) を今すぐ最新にする
    python -m src.remediation plan      # 今すぐ計画する (updater に依頼を出す)
    python -m src.remediation collect   # updater の結果を今すぐ回収する (差分検査・PR)
    python -m src.remediation track     # PR・デプロイ・照合を今すぐ追う
    python -m src.remediation retry [--service]  # 前に失敗した版の記録を消して、次の計画でやり直させる
    python -m src.remediation status    # 写しと改修の状態 (読み取りのみ)
    python -m src.remediation updater   # 隔離した更新役の常駐 (remediation-updater コンテナ)
    python -m src.remediation egress    # updater の通信を PyPI だけに絞るプロキシ (remediation-egress コンテナ)

remediation.db にだけ書く。GitHub のトークン (REMEDIATION_GITHUB_TOKEN) は config/remediation.env から
remediation コンテナにだけ渡す (updater・egress には渡さない)。
書き込みを伴うコマンドは data/.locks/remediation.lock を取ってから動く。
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import typer
from sqlalchemy import Engine, text

from ..common.db import make_engine
from ..common.http import make_client
from ..common.lock import writer_lock
from ..common.migrate import upgrade
from ..common.paths import default_paths
from ..common.scheduler import Job, Scheduler
from ..config import settings
from ..detection.triage import PRIORITIES
from . import egress as egress_mod
from . import updater as updater_mod
from .github import GitHub
from .mirror import MainMirror, current_sha
from .pipeline import (
    JOB_COLLECT,
    JOB_MIRROR,
    JOB_PLAN,
    JOB_TRACK,
    RemediationPipeline,
    RemediationSettings,
)

app = typer.Typer(add_completion=False, help="B 自動改修")


def _readonly(name: str) -> Callable[[], Engine | None]:
    def get() -> Engine | None:  # 起動後に作られた DB も拾えるよう、毎回確かめる
        path = default_paths().sqlite_path(name)
        return make_engine(path, read_only=True) if path.exists() else None
    return get


def build_pipeline() -> RemediationPipeline:
    if settings.remediation_min_priority not in PRIORITIES:
        raise typer.BadParameter(f"REMEDIATION_MIN_PRIORITY は {'/'.join(PRIORITIES)} のどれか")
    paths = default_paths()
    upgrade("remediation", paths)
    github = GitHub(make_client(), settings.remediation_repo, settings.remediation_github_token)
    mirror = MainMirror(github, paths.remediation_dir, settings.remediation_branch,
                        settings.remediation_mirror_max_mb * 2**20)
    return RemediationPipeline(
        make_engine(paths.sqlite_path("remediation")), mirror, detection=_readonly("detection"),
        intel=_readonly("intel"), jobs_dir=paths.remediation_dir / "jobs", events_dir=paths.events_dir,
        cfg=RemediationSettings(
            min_priority=settings.remediation_min_priority, open_prs=settings.remediation_open_prs,
            token_warn_days=settings.remediation_token_warn_days, base_branch=settings.remediation_branch,
        ),
    )


def locked[T](fn: Callable[[], T]) -> Callable[[], T]:
    def run() -> T:
        with writer_lock(default_paths().root, "remediation"):
            return fn()

    return run


@app.callback()
def _setup(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@app.command()
def mirror() -> None:
    pipeline = build_pipeline()
    locked(pipeline.run_mirror)()
    typer.echo(f"main = {pipeline.mirror.current()}")


@app.command()
def plan() -> None:
    locked(build_pipeline().run_plan)()


@app.command()
def collect() -> None:
    locked(build_pipeline().run_collect)()


@app.command()
def track() -> None:
    locked(build_pipeline().run_track)()


@app.command()
def retry(service: str = typer.Option(None, help="このサービスだけ (省略すると全部)")) -> None:
    """前に失敗した (パッケージ, 版) の記録と、1 つずつにしたまとめ方を消して、次の計画でやり直させる。"""
    pipeline = build_pipeline()

    def clear() -> tuple[int, int]:
        where, params = (" WHERE service_id = :s", {"s": service}) if service else ("", {})
        with pipeline.engine.begin() as conn:
            a = conn.execute(text("DELETE FROM attempts" + where), params).rowcount  # nosec B608
            m = conn.execute(text("DELETE FROM service_modes" + where), params).rowcount  # nosec B608
        return a, m

    attempts, modes = locked(clear)()
    typer.echo(f"cleared {attempts} attempts, {modes} service modes")


@app.command()
def status(limit: int = typer.Option(20, help="表示する改修の件数 (新しい順)")) -> None:
    paths = default_paths()
    path = paths.sqlite_path("remediation")
    typer.echo(f"main: {paths.main_mirror_dir} -> {current_sha(paths.remediation_dir) or '(なし)'}")
    typer.echo(f"PR を作る: {'はい' if settings.remediation_open_prs else 'いいえ (dry_run)'}")
    if not path.exists():
        return
    with make_engine(path, read_only=True).connect() as conn:
        for job in (JOB_MIRROR, JOB_PLAN, JOB_COLLECT, JOB_TRACK):
            row = conn.execute(text(
                "SELECT finished_at, detail FROM job_runs WHERE job = :j AND status = 'success' "
                "ORDER BY finished_at DESC LIMIT 1"), {"j": job}).first()
            typer.echo(f"{job:8} {row[0] if row else '-'} {json.loads(row[1] or '{}') if row else ''}")
        rows = conn.execute(text(
            "SELECT created_at, run_id, service_id, status, mode, manual, pr_url, deploy_status, packages_json, "
            "detail_json FROM runs ORDER BY created_at DESC LIMIT :n"), {"n": limit}).all()
    for created, run_id, svc, st, mode, manual, pr_url, deploy, packages, detail in rows:
        pkgs = ", ".join(f"{p['name']} {p['current']}→{p['target']}" for p in json.loads(packages))
        d = json.loads(detail or "{}")
        extra = d.get("reason") or ""
        typer.echo(f"{created[:16]} {run_id} {svc:24} {st:13} {mode}{' manual' if manual else ''} "
                   f"deploy={deploy or '-'} {pr_url or ''}\n    {pkgs}{(chr(10) + '    ' + extra) if extra else ''}")


@app.command()
def updater() -> None:
    """隔離した更新役 (トークン・DB を持たない)。jobs/in を読み、jobs/out に書く。"""
    jobs = default_paths().remediation_dir / "jobs"
    work = Path("/tmp/work")  # nosec B108  コンテナの tmpfs (毎回まっさら)
    work.mkdir(parents=True, exist_ok=True)
    (jobs / "out").mkdir(parents=True, exist_ok=True)
    updater_mod.serve(jobs / "in", jobs / "out", work)


@app.command()
def egress(host: str = typer.Option("0.0.0.0", help="待ち受けるアドレス"),  # nosec B104  内部ネットワークだけ
           port: int = typer.Option(3128)) -> None:
    egress_mod.serve(host, port, egress_mod.parse_allow(settings.remediation_egress_allow))


@app.command()
def serve() -> None:
    pipeline = build_pipeline()
    jobs = [
        Job(JOB_MIRROR, timedelta(minutes=settings.remediation_mirror_interval_minutes), locked(pipeline.run_mirror)),
        Job(JOB_PLAN, timedelta(minutes=settings.remediation_plan_interval_minutes), locked(pipeline.run_plan)),
        Job(JOB_COLLECT, timedelta(minutes=5), locked(pipeline.run_collect)),
        Job(JOB_TRACK, timedelta(minutes=10), locked(pipeline.run_track)),
    ]
    Scheduler(jobs, pipeline.last_success).run_forever()


if __name__ == "__main__":
    app()
