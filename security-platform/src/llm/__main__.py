"""L4 の記事の抽出 (extractor サービス) の CLI。

    python -m src.llm serve          # docker compose 用の常駐 (夜の時間帯だけ動く)
    python -m src.llm run [--limit]  # 今すぐ処理する (1 日の上限は守る)
    python -m src.llm check          # トークンで LLM を呼べるか確かめる (架空の記事 1 件)
    python -m src.llm eval           # 評価用の記事 (eval_cases.json) で抜き出しの精度を見る

DB には触らない。data/llm/in/ を読み、data/llm/out/ と data/llm/state/ に書くだけ。
"""
from __future__ import annotations

import logging
import signal
import time

import typer

from ..common.paths import default_paths
from ..common.timeutil import utc_now
from .config import LlmSettings
from .eval import CHECK_CASE, load_cases, score
from .providers import Extractor, ProviderUnavailable, make_extractor
from .worker import LlmDirs, Window, run_batch

logger = logging.getLogger(__name__)
app = typer.Typer(add_completion=False, help="L4 記事の抽出")

POLL_SECONDS = 600


def _setup() -> tuple[LlmSettings, Extractor, LlmDirs, Window]:
    s = LlmSettings()
    root = default_paths().llm_dir
    extractor = make_extractor(s.provider, s.model, token=s.claude_code_oauth_token, binary=s.claude_binary)
    return s, extractor, LlmDirs(root / "in", root / "out", root / "state"), Window(
        s.daily_limit, s.run_hour, s.window_hours, s.timezone)


@app.callback()
def _logging(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")


@app.command()
def run(limit: int = typer.Option(None, help="処理する件数 (省略時はその日の残り回数まで)")) -> None:
    _, extractor, dirs, window = _setup()
    r = run_batch(extractor, dirs, window, utc_now(), limit)
    typer.echo(f"done={r.done} failed={r.failed} pending={r.pending} stopped={r.stopped or '-'}")
    raise typer.Exit(1 if r.stopped else 0)


@app.command()
def check() -> None:
    """架空の記事 1 件で LLM を呼ぶ (1 日の回数には数えない)。"""
    s, extractor, _, _ = _setup()
    try:
        out = extractor.extract(CHECK_CASE.item())
    except ProviderUnavailable as e:
        typer.echo(f"NG    {s.provider} ({s.model}): {e}")
        raise typer.Exit(1) from None
    names = [c["package"] for c in out["claims"]]
    typer.echo(f"OK    {s.provider} ({s.model}): claims={names}")


@app.command("eval")
def eval_(case: str = typer.Option(None, help="この id の記事だけ")) -> None:
    """評価用の記事で抜き出し → 原文との突き合わせまで行い、期待との一致を表示する (1 日の回数には数えない)。"""
    s, extractor, _, _ = _setup()
    cases = [c for c in load_cases() if case is None or c.id == case]
    total = score(extractor, cases, typer.echo)
    typer.echo(f"\n{s.provider} ({s.model}): precision={total.precision:.2f} recall={total.recall:.2f} "
               f"ungrounded={total.ungrounded} errors={total.errors}")
    raise typer.Exit(1 if total.errors else 0)


@app.command()
def serve() -> None:
    """夜の時間帯に入ったら処理する。止まった (上限・認証) ら、その時間帯はもう呼ばない。"""
    s, extractor, dirs, window = _setup()
    stopping = False

    def stop(*_: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    logger.info("extractor: %s (%s), %d/day from %02d:00 %s for %dh", s.provider, s.model, s.daily_limit,
                s.run_hour, s.timezone, s.window_hours)
    paused_day = None
    while not stopping:
        now = utc_now()
        day = window.local(now).date()
        if window.is_open(now) and paused_day != day:
            r = run_batch(extractor, dirs, window, now)
            if r.stopped:
                paused_day = day
        deadline = time.monotonic() + POLL_SECONDS
        while not stopping and time.monotonic() < deadline:
            time.sleep(1.0)
    logger.info("extractor stopped")


if __name__ == "__main__":
    app()
