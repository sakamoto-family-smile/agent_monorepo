"""updater (隔離した更新役): ``uv lock --upgrade-package`` で uv.lock だけを書き換える。

    python -m src.remediation updater   # docker compose 用の常駐 (jobs/in を見て jobs/out に書く)

パッケージのビルドでそのパッケージのコードが動きうるので、このコンテナは次の条件で動かす
(docker-compose.yml の remediation-updater):

- トークン・DB・モノレポの作業コピーを持たない。読めるのは jobs/in (読み取り専用) だけ、書けるのは jobs/out だけ
- 外への通信は egress プロキシ経由で PyPI (pypi.org / files.pythonhosted.org) だけ
- ルートファイルシステムは読み取り専用、作業は tmpfs (毎回まっさら)

uv の結果は remediation が差分検査にかけてから PR にするので、ここでは判断しない。
全部まとめて上げられなければ 1 つずつ試し、上げられたものだけで作り直す
(制約に引っかかったパッケージは failed として返す)。
"""
from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess  # nosec B404  uv を引数のリストで呼ぶだけ (シェルは通さない)
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..common.timeutil import to_iso, utc_now
from .jobs import InvalidJob, UpdateJob, UpdateResult, list_jobs, read_job, write_result

logger = logging.getLogger(__name__)

POLL_SECONDS = 30
UV_TIMEOUT_SECONDS = 600
OUTPUT_TAIL = 4000


@dataclass(frozen=True)
class UvRun:
    ok: bool
    output: str


Runner = Callable[[Path, list[tuple[str, str]]], UvRun]


def uv_runner(uv: str = "uv", timeout: int = UV_TIMEOUT_SECONDS) -> Runner:
    def run(project_dir: Path, packages: list[tuple[str, str]]) -> UvRun:
        args = [uv, "lock", "--project", str(project_dir), "--no-progress"]
        for name, version in packages:
            args += ["--upgrade-package", f"{name}=={version}"]
        env = {
            # /tmp はコンテナの tmpfs (毎回まっさら)
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.environ.get("HOME", "/tmp"),  # nosec B108
            "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", "/tmp/uv-cache"),  # nosec B108
            "UV_PYTHON_DOWNLOADS": "never",  # Python 本体は取りに行かない (イメージの Python を使う)
            "NO_COLOR": "1",
        }
        for k in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "SSL_CERT_FILE", "UV_PYTHON_INSTALL_DIR"):
            if k in os.environ:
                env[k] = os.environ[k]
        try:
            p = subprocess.run(args, env=env, capture_output=True, text=True, timeout=timeout,  # nosec B603
                               check=False)
        except subprocess.TimeoutExpired:
            return UvRun(False, f"uv lock timed out after {timeout}s")
        except OSError as e:
            return UvRun(False, f"uv could not be started: {e}")
        return UvRun(p.returncode == 0, (p.stdout + p.stderr)[-OUTPUT_TAIL:])
    return run


def uv_version(uv: str = "uv") -> str:
    try:
        return subprocess.run([uv, "--version"], capture_output=True, text=True, timeout=30,  # nosec B603
                              check=False).stdout.strip()[:100]
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _attempt(tree: Path, job: UpdateJob, packages: list[tuple[str, str]], runner: Runner,
             work_root: Path) -> tuple[UvRun, str | None]:
    """tree をまっさらな作業ディレクトリに写してから uv lock する。成功すれば新しい uv.lock の中身も返す。"""
    work = Path(tempfile.mkdtemp(prefix="job-", dir=work_root))
    try:
        shutil.copytree(tree, work / "tree", symlinks=True)
        project = work / "tree" / job.project
        r = runner(project, packages)
        lock = (project / "uv.lock").read_text(encoding="utf-8") if r.ok else None
        return r, lock
    finally:
        shutil.rmtree(work, ignore_errors=True)


def process(job: UpdateJob, tree: Path, runner: Runner, work_root: Path) -> UpdateResult:
    packages = list(job.packages)
    log: list[str] = []
    r, lock = _attempt(tree, job, packages, runner, work_root)
    log.append(f"$ all ({len(packages)})\n{r.output}")
    if r.ok:
        return UpdateResult(job.run_id, True, lock, tuple(n for n, _ in packages), log="\n".join(log))
    if len(packages) == 1:
        return UpdateResult(job.run_id, False, None, (), ((packages[0][0], r.output),), log="\n".join(log))
    ok: list[tuple[str, str]] = []
    failed: list[tuple[str, str]] = []  # (名前, uv の出力)
    for name, version in packages:  # どれが引っかかったかを 1 つずつ確かめる
        one, _ = _attempt(tree, job, [(name, version)], runner, work_root)
        log.append(f"$ {name}=={version}\n{one.output}")
        if one.ok:
            ok.append((name, version))
        else:
            failed.append((name, one.output))
    if not ok:
        return UpdateResult(job.run_id, False, None, (), tuple(failed), log="\n".join(log))
    r, lock = _attempt(tree, job, ok, runner, work_root)
    log.append(f"$ ok ({len(ok)})\n{r.output}")
    if not r.ok:  # 1 つずつなら通るのに、合わせると通らない
        conflicts = tuple((n, "conflicts with the other upgrades") for n, _ in ok)
        return UpdateResult(job.run_id, False, None, (), tuple(failed) + conflicts, log="\n".join(log))
    return UpdateResult(job.run_id, True, lock, tuple(n for n, _ in ok), tuple(failed), log="\n".join(log))


def run_pending(in_dir: Path, out_dir: Path, runner: Runner, work_root: Path, version: str = "") -> int:
    """in にあって out にない依頼を古い順に処理する。処理した件数を返す。"""
    done = 0
    for run_id in list_jobs(in_dir):
        if (out_dir / f"{run_id}.json").exists():
            continue
        try:
            job = read_job(in_dir, run_id)
            tree = in_dir / run_id / "tree"
            if not tree.is_dir():
                raise InvalidJob(f"{run_id}: tree is missing")
            result = process(job, tree, runner, work_root)
        except (InvalidJob, OSError) as e:
            result = UpdateResult(run_id, False, None, error=f"{type(e).__name__}: {e}"[:2000])
        result = UpdateResult(**{**result.__dict__, "uv_version": version, "finished_at": to_iso(utc_now())})
        write_result(out_dir, result)
        logger.info("update %s: ok=%s applied=%d failed=%d", run_id, result.ok, len(result.applied),
                    len(result.failed))
        done += 1
    return done


def serve(in_dir: Path, out_dir: Path, work_root: Path, uv: str = "uv") -> None:
    stopping = False

    def stop(*_: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    version = uv_version(uv)
    logger.info("updater: %s, in=%s out=%s", version or "uv not found", in_dir, out_dir)
    runner = uv_runner(uv)
    while not stopping:
        try:
            run_pending(in_dir, out_dir, runner, work_root, version)
        except Exception:  # 1 回の失敗で常駐を止めない
            logger.exception("updater loop failed")
        deadline = time.monotonic() + POLL_SECONDS
        while not stopping and time.monotonic() < deadline:
            time.sleep(1.0)
    logger.info("updater stopped")
