"""A2 内部該当検知の CLI。

    python -m src.detection scan        # 全サービスの lockfile・本番イメージを照合して findings を更新
    python -m src.detection findings    # 未対応の Finding を優先度順に表示 (読み取りのみ)
    python -m src.detection serve       # docker compose 用の常駐 (定期的に scan)
    python -m src.detection images      # 本番イメージの SBOM を作る (ホストで実行)
    python -m src.detection exceptions add|list|revoke   # 例外 (誤検知・リスク受容) の管理

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
from ..common.timeutil import parse_iso, utc_now
from ..config import settings
from .exceptions import KINDS, ExceptionStore
from .images import ImageSbomFetcher
from .pipeline import JOB_SCAN, DetectionPipeline

app = typer.Typer(add_completion=False, help="A2 内部該当検知")
exceptions_app = typer.Typer(add_completion=False, help="例外 (誤検知・リスク受容)。次の scan で反映される")
app.add_typer(exceptions_app, name="exceptions")


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


@exceptions_app.command("add")
def exceptions_add(
    advisory: str = typer.Option(..., help="Advisory の ID (CVE 番号など)"),
    reason: str = typer.Option(..., help="例外にする理由"),
    kind: str = typer.Option(..., help=" / ".join(KINDS)),
    service: str = typer.Option("*", help="サービス ID。* なら全サービス"),
    package: str | None = typer.Option(None, help="パッケージ名。省略するとその Advisory の全パッケージ"),
    expires: str | None = typer.Option(None, help="期限 (例: 2026-12-31)。risk_accepted は必須"),
) -> None:
    expires_at = parse_iso(f"{expires}T00:00:00Z" if expires and "T" not in expires else expires) \
        if expires else None
    store = ExceptionStore(build_pipeline().engine)
    try:
        exc = locked(lambda: store.add(service, advisory, package, kind, reason, expires_at))()
    except ValueError as e:
        typer.echo(f"ERROR {e}")
        raise typer.Exit(1) from None
    typer.echo(f"added {exc.exception_id} (次の scan で反映)")


@exceptions_app.command("list")
def exceptions_list(all_: bool = typer.Option(False, "--all", help="期限切れ・取り消し済みも表示")) -> None:
    now = utc_now()
    for e in ExceptionStore(build_pipeline(read_only=True).engine).all():
        if not all_ and not e.active(now):
            continue
        state = "active" if e.active(now) else ("revoked" if e.revoked_at else "expired")
        until = e.expires_at.date().isoformat() if e.expires_at else "-"
        typer.echo(f"{e.exception_id} {state:7} {e.kind:14} {e.service_id:24} {e.advisory_id} "
                   f"{e.package or '*'} until={until} {e.reason}")


@exceptions_app.command("revoke")
def exceptions_revoke(exception_id: str) -> None:
    store = ExceptionStore(build_pipeline().engine)
    if not locked(lambda: store.revoke(exception_id))():
        typer.echo(f"ERROR {exception_id} は無いか、取り消し済み")
        raise typer.Exit(1)
    typer.echo(f"revoked {exception_id} (次の scan で open に戻る)")


@app.command()
def serve() -> None:
    pipeline = build_pipeline()
    interval = timedelta(minutes=settings.detection_scan_interval_minutes)

    def run() -> None:
        locked(pipeline.run_scan)()

    Scheduler([Job(JOB_SCAN, interval, run)], pipeline.last_success).run_forever()


if __name__ == "__main__":
    app()
