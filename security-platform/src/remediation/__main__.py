"""B 自動改修 (remediation サービス) の CLI。

    python -m src.remediation serve     # docker compose 用の常駐
    python -m src.remediation mirror    # origin/main の写し (data/remediation/main) を今すぐ最新にする
    python -m src.remediation status    # 写しのコミットと最終更新 (読み取りのみ)

remediation.db にだけ書く。GitHub のトークン (REMEDIATION_GITHUB_TOKEN) は config/remediation.env から
このコンテナにだけ渡す。書き込みを伴うコマンドは data/.locks/remediation.lock を取ってから動く。
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import timedelta

import typer
from sqlalchemy import text

from ..common.db import make_engine
from ..common.http import make_client
from ..common.lock import writer_lock
from ..common.migrate import upgrade
from ..common.paths import default_paths
from ..common.scheduler import Job, Scheduler
from ..config import settings
from .github import GitHub
from .mirror import MainMirror, current_sha
from .pipeline import JOB_MIRROR, RemediationPipeline

app = typer.Typer(add_completion=False, help="B 自動改修")


def build_pipeline() -> RemediationPipeline:
    paths = default_paths()
    upgrade("remediation", paths)
    github = GitHub(make_client(), settings.remediation_repo, settings.remediation_github_token)
    mirror = MainMirror(github, paths.remediation_dir, settings.remediation_branch,
                        settings.remediation_mirror_max_mb * 2**20)
    return RemediationPipeline(make_engine(paths.sqlite_path("remediation")), mirror)


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
def status() -> None:
    paths = default_paths()
    path = paths.sqlite_path("remediation")
    typer.echo(f"main: {paths.main_mirror_dir} -> {current_sha(paths.remediation_dir) or '(なし)'}")
    if not path.exists():
        return
    with make_engine(path, read_only=True).connect() as conn:
        row = conn.execute(text(
            "SELECT finished_at, detail FROM job_runs WHERE job = :j AND status = 'success' "
            "ORDER BY finished_at DESC LIMIT 1"), {"j": JOB_MIRROR}).first()
    if row:
        typer.echo(f"last sync: {row[0]} {json.loads(row[1] or '{}')}")


@app.command()
def serve() -> None:
    pipeline = build_pipeline()
    interval = timedelta(minutes=settings.remediation_mirror_interval_minutes)
    Scheduler([Job(JOB_MIRROR, interval, locked(pipeline.run_mirror))], pipeline.last_success).run_forever()


if __name__ == "__main__":
    app()
