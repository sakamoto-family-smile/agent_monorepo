"""分析 DB の CLI。

    python -m src.analytics build     # dbt build → security.duckdb を差し替え
    python -m src.analytics serve     # docker compose 用の常駐 (定期 build)
    python -m src.analytics ui        # DuckDB UI (ブラウザの SQL ノートブック) を読み取り専用で開く
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta

import typer

from ..common.paths import default_paths
from ..common.scheduler import Job, Scheduler
from ..config import settings
from .build import build as build_analytics
from .build import last_success

logger = logging.getLogger(__name__)
app = typer.Typer(add_completion=False, help="分析 DB (DuckDB)")


@app.callback()
def _setup() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@app.command()
def build() -> None:
    typer.echo(str(build_analytics(default_paths())))


@app.command()
def serve() -> None:
    paths = default_paths()
    job = Job("analytics", timedelta(minutes=settings.analytics_interval_minutes),
              lambda: build_analytics(paths))
    Scheduler([job], lambda _name: last_success(paths)).run_forever()


@app.command()
def ui() -> None:
    """security.duckdb を読み取り専用で開き、DuckDB UI を起動する (Ctrl+C で終了)。"""
    import duckdb

    path = default_paths().duckdb_path
    if not path.exists():
        raise typer.BadParameter(f"{path} がありません。先に `make analytics` を実行してください")
    con = duckdb.connect(str(path), read_only=True)
    con.execute("CALL start_ui()")
    typer.echo("DuckDB UI: http://localhost:4213  (Ctrl+C で終了)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        con.close()


if __name__ == "__main__":
    app()
