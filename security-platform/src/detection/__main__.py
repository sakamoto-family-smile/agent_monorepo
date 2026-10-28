"""A2 内部該当検知の CLI。

    python -m src.detection scan        # 全サービスの lockfile・本番イメージを照合して findings を更新
    python -m src.detection findings    # 未対応の Finding を優先度順に表示 (読み取りのみ)
    python -m src.detection serve       # docker compose 用の常駐 (定期的に scan)
    python -m src.detection images      # 本番イメージの SBOM を作る (ホストで実行)

書き込みを伴うコマンドは data/.locks/detection.lock を取ってから動く。
images 以外はホストの macOS からは実行せず、``make detection-*`` (= docker compose run) を使う。
images は gcloud と docker を使うのでホストで実行する (``make detection-images``)。SQLite には触らない。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import typer

from ..common.db import make_engine
from ..common.lock import writer_lock
from ..common.migrate import upgrade
from ..common.paths import default_paths
from ..common.scheduler import Job, Scheduler
from ..common.services import load_services
from ..config import settings
from .images import ImageSbomFetcher
from .pipeline import JOB_SCAN, DetectionPipeline

app = typer.Typer(add_completion=False, help="A2 内部該当検知")


def build_pipeline(*, read_only: bool = False) -> DetectionPipeline:
    paths = default_paths()
    if not read_only:
        upgrade("detection", paths)
    return DetectionPipeline(
        make_engine(paths.sqlite_path("detection"), read_only=read_only),
        make_engine(paths.sqlite_path("intel"), read_only=True),
        paths,
        settings.repo_dir,
        load_services(settings.services_path),
        timedelta(days=settings.image_sbom_max_age_days),
    )


def locked[T](fn: Callable[[], T]) -> Callable[[], T]:
    def run() -> T:
        with writer_lock(default_paths().root, "detection"):
            return fn()

    return run


@app.callback()
def _setup(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@app.command()
def scan() -> None:
    r = locked(build_pipeline().run_scan)()
    typer.echo(f"{r.services} services / {r.components} components / open {r.open_findings} "
               f"(+{r.opened} ~{r.updated} -{r.resolved})")
    for w in r.warnings:
        typer.echo(f"WARN {w}")


@app.command()
def findings() -> None:
    """未対応の Finding を優先度・期限順に表示する。"""
    rows = build_pipeline(read_only=True).open_findings()
    for f in rows:
        fix = f"→ {f['fixed_version']}" if f["fixed_version"] else "修正版なし"
        due = (f["due_at"] or "-")[:10]
        typer.echo(f"{f['priority']} {due} {f['service_id']:26} {f['package']}=={f['version']} {fix} "
                   f"[{f['advisory_id']}] {'; '.join(f['reasons'])}")
    typer.echo(f"{len(rows)} open")


@app.command()
def images() -> None:
    """Cloud Run で動いている本番イメージの SBOM を作る (gcloud・docker を使うのでホストで実行)。"""
    paths = default_paths()
    fetcher = ImageSbomFetcher(paths.sbom_images_dir, settings.syft_image, settings.gcp_project)
    r = fetcher.fetch(load_services(Path(settings.services_path)))
    typer.echo(f"{r.services} services / {r.images} images (新規 SBOM {r.generated}, 削除 {r.removed})")
    for e in r.errors:
        typer.echo(f"ERROR {e}")
    if r.errors:
        raise typer.Exit(1)


@app.command()
def serve() -> None:
    pipeline = build_pipeline()
    interval = timedelta(minutes=settings.detection_scan_interval_minutes)

    def run() -> None:
        locked(pipeline.run_scan)()

    Scheduler([Job(JOB_SCAN, interval, run)], pipeline.last_success).run_forever()


if __name__ == "__main__":
    app()
