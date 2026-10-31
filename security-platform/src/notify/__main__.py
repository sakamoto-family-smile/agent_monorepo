"""通知 (notify サービス) の CLI。

    python -m src.notify serve    # docker compose 用の常駐 (P1 の即時通知・監視・日次まとめ・Issues)
    python -m src.notify test     # LINE にテストメッセージを送る
    python -m src.notify digest   # 日次まとめを今すぐ送る (その日にまだ送っていなければ)
    python -m src.notify issues   # GitHub Issues を今すぐ同期する
    python -m src.notify health   # 監視項目の今の状態を表示する (送らない)

notify.db にだけ書く。detection.db・intel.db は読み取り専用。送り先の認証情報は
config/notify.env からこのコンテナにだけ渡す (他のサービスには渡さない)。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from zoneinfo import ZoneInfo

import typer

from ..common.db import make_engine
from ..common.healthcheck import make_pinger
from ..common.http import make_client
from ..common.lock import writer_lock
from ..common.migrate import upgrade
from ..common.paths import default_paths
from ..common.scheduler import Job, Scheduler
from ..common.timeutil import utc_now
from ..config import settings
from ..detection.triage import PRIORITIES
from ..intel.schedule import schedule
from .channels import GitHubIssues, LineChannel
from .pipeline import JOB_DIGEST, JOB_EVENTS, JOB_HEALTH, JOB_ISSUES, NotifyPipeline, NotifySettings

app = typer.Typer(add_completion=False, help="脆弱性対応の通知")


def build_pipeline() -> NotifyPipeline:
    if settings.notify_issue_min_priority not in PRIORITIES:
        raise typer.BadParameter(f"NOTIFY_ISSUE_MIN_PRIORITY は {'/'.join(PRIORITIES)} のどれか")
    paths = default_paths()
    upgrade("notify", paths)
    client = make_client()

    def readonly(name: str) -> Callable[[], object]:
        def get():  # noqa: ANN202  起動後に作られた DB も拾えるよう、毎回確かめる
            path = paths.sqlite_path(name)
            return make_engine(path, read_only=True) if path.exists() else None
        return get

    recipients = [u.strip() for u in settings.line_user_ids.split(",") if u.strip()]
    return NotifyPipeline(
        make_engine(paths.sqlite_path("notify")), readonly("detection"), readonly("intel"),  # type: ignore[arg-type]
        paths.sbom_images_dir,
        LineChannel(client, settings.line_channel_access_token, recipients),
        GitHubIssues(client, settings.github_issues_token, settings.github_issues_repo),
        NotifySettings(
            ZoneInfo(settings.notify_timezone), settings.notify_digest_hour, settings.notify_issue_min_priority,
            timedelta(minutes=settings.detection_scan_interval_minutes),
            timedelta(days=settings.image_sbom_max_age_days), schedule(),
            timedelta(hours=settings.host_inventory_max_age_hours),
        ),
        paths.sbom_hosts_dir,
    )


def locked[T](fn: Callable[[], T]) -> Callable[[], T]:
    def run() -> T:
        with writer_lock(default_paths().root, "notify"):
            return fn()

    return run


@app.callback()
def _setup(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # リクエスト URL を INFO で出すので止める (Healthchecks の Ping key が URL に入る)
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


@app.command()
def test() -> None:
    p = build_pipeline()
    typer.echo(locked(p.send_test)())


@app.command()
def digest() -> None:
    p = build_pipeline()
    locked(lambda: p.run_digest(force=True))()


@app.command()
def issues() -> None:
    locked(build_pipeline().run_issues)()


@app.command()
def health() -> None:
    for c in build_pipeline().checks(utc_now()):
        typer.echo(f"{'OK   ' if c.ok else 'STALE'} {c.key:32} {c.detail}")


@app.command()
def serve() -> None:
    p = build_pipeline()
    jobs = [
        Job(JOB_EVENTS, timedelta(minutes=5), locked(p.run_events)),
        Job(JOB_HEALTH, timedelta(minutes=30), locked(p.run_health)),
        Job(JOB_DIGEST, timedelta(minutes=15), locked(p.run_digest)),
        Job(JOB_ISSUES, timedelta(minutes=30), locked(p.run_issues)),
    ]
    pinger = make_pinger(make_client(), settings.healthcheck_ping_base)
    Scheduler(jobs, p.last_success, on_result=pinger).run_forever()


if __name__ == "__main__":
    app()
