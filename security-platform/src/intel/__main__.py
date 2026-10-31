"""A1 情報取得の CLI。

    python -m src.intel bootstrap     # 初回全量 (中断しても再開できる)
    python -m src.intel osv           # OSV 差分
    python -m src.intel osv-full      # OSV 全量の再取得
    python -m src.intel kev / epss
    python -m src.intel health        # 情報源ごとの最終成功時刻 (読み取りのみ)
    python -m src.intel serve         # docker compose 用の常駐 (ブートストラップ → 定期実行)

書き込みを伴うコマンドは data/.locks/intel.lock を取ってから動く (serve もジョブごとに取る)。
ホストの macOS からは実行せず、``make intel-*`` (= docker compose run) を使う。
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import timedelta

import typer

from ..common.db import make_engine
from ..common.healthcheck import make_pinger
from ..common.http import make_client, with_retry
from ..common.lock import writer_lock
from ..common.migrate import upgrade
from ..common.paths import default_paths
from ..common.scheduler import Job, Scheduler
from ..common.timeutil import utc_now
from ..config import settings
from .pipeline import IntelPipeline
from .schedule import STALE_FACTOR, schedule
from .sources.osv import OsvClient

logger = logging.getLogger(__name__)
app = typer.Typer(add_completion=False, help="A1 情報取得")

BOOTSTRAP_RETRY_SECONDS = 300


def build_pipeline(*, read_only: bool = False) -> IntelPipeline:
    paths = default_paths()
    if not read_only:
        upgrade("intel", paths)
    client = make_client()

    def fetch_bytes(url: str) -> bytes:
        def go() -> bytes:
            r = client.get(url)
            r.raise_for_status()
            return r.content

        return with_retry(go, what=url)

    ecosystems = [e.strip() for e in settings.osv_ecosystems.split(",") if e.strip()] or None
    return IntelPipeline(
        make_engine(paths.sqlite_path("intel"), read_only=read_only),
        paths,
        OsvClient(client, settings.osv_base_url),
        fetch_bytes,
        kev_url=settings.kev_url,
        epss_url=settings.epss_url,
        epss_delta=settings.epss_event_delta,
        incremental_max_per_ecosystem=settings.osv_incremental_max_records,
        full_snapshots_kept=settings.osv_raw_full_snapshots_kept,
        ecosystems=ecosystems,
        raw_retention=timedelta(days=settings.raw_retention_days),
        min_free_bytes=int(settings.min_free_disk_gb * 1e9),
    )


def locked[T](fn: Callable[[], T]) -> Callable[[], T]:
    def run() -> T:
        with writer_lock(default_paths().root, "intel"):
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
def bootstrap() -> None:
    """初回の全量取り込み。完了済みなら何もしない。"""
    ran = locked(build_pipeline().bootstrap)()
    typer.echo("bootstrap completed" if ran else "already bootstrapped")


@app.command()
def osv() -> None:
    locked(build_pipeline().run_osv_incremental)()


@app.command("osv-full")
def osv_full() -> None:
    locked(build_pipeline().run_osv_full)()


@app.command()
def kev() -> None:
    locked(build_pipeline().run_kev)()


@app.command()
def epss() -> None:
    locked(build_pipeline().run_epss)()


@app.command()
def health() -> None:
    """間隔の 3 倍以上成功していない情報源があれば終了コード 1。DB には書かない。"""
    try:
        pipeline = build_pipeline(read_only=True)
    except FileNotFoundError:
        typer.echo("STALE intel.db がありません (bootstrap 前)")
        raise typer.Exit(1) from None
    stale = False
    now = utc_now()
    for source, interval in schedule().items():
        last = pipeline.last_success(source)
        ok = last is not None and now - last < interval * STALE_FACTOR
        stale |= not ok
        typer.echo(f"{'OK   ' if ok else 'STALE'} {source:9} last_success={last}")
    missing = pipeline.missing_count()
    if missing:
        typer.echo(f"WARN  osv_missing={missing} (modified_id.csv にあるが本文が 404 のレコード)")
    raise typer.Exit(1 if stale else 0)


@app.command()
def serve() -> None:
    """ブートストラップを終えるまで再試行し、その後は定期実行する。"""
    pipeline = build_pipeline()
    pinger = make_pinger(make_client(), settings.healthcheck_ping_base)
    while True:
        try:
            locked(pipeline.bootstrap)()
            break
        except Exception:
            logger.exception("bootstrap failed; retrying in %ss", BOOTSTRAP_RETRY_SECONDS)
            time.sleep(BOOTSTRAP_RETRY_SECONDS)
    runners = {
        "osv": pipeline.run_osv_incremental,
        "kev": pipeline.run_kev,
        "epss": pipeline.run_epss,
        "osv_full": pipeline.run_osv_full,
    }
    jobs = [Job(name, interval, locked(runners[name])) for name, interval in schedule().items()]
    Scheduler(jobs, pipeline.last_success, on_result=pinger).run_forever()


if __name__ == "__main__":
    app()
