"""remediation と updater (隔離した更新役) のファイルのやり取り (data/remediation/jobs/)。

    in/<run_id>/tree/       remediation が書く。写しから取り出した対象のサービスと path 依存のディレクトリ
    in/<run_id>.json        remediation が書く (tree を書き終えてから)。上げるパッケージと版
    out/<run_id>.json       updater が書く。更新後の uv.lock (の中身) と、上げられなかったパッケージ

updater はパッケージのビルド (sdist の setup.py など) でパッケージ自身のコードを動かしうるので、
トークンも DB も持たず、通信はパッケージの取得先だけに絞ったコンテナで動かす。
ここで受け取る out は信頼しない入力として扱い、remediation が差分検査 (guard) にかけてから使う。
書き込みは一時ファイルからの rename で、読み手が書きかけのファイルを見ないようにする。
"""
from __future__ import annotations

import json
import re
import shutil
import tomllib
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from ..llm.exchange import write_json

FORMAT = 1
RUN_ID = re.compile(r"^rem_[0-9a-f]{16}$")
# PEP 508 の名前と PEP 440 の版 (uv にそのまま渡すので、引数として安全な文字だけにする)
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
VERSION = re.compile(r"^[0-9][0-9A-Za-z.+!_-]{0,63}$")
PROJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
MAX_JOB_BYTES = 100_000
MAX_RESULT_BYTES = 8_000_000  # uv.lock は大きいものでも数 MB
IGNORE = shutil.ignore_patterns(".venv", "node_modules", "__pycache__", ".git")


class InvalidJob(ValueError):
    pass


def new_run_id() -> str:
    return f"rem_{uuid.uuid4().hex[:16]}"


@dataclass(frozen=True)
class UpdateJob:
    run_id: str
    project: str  # tree の中のサービスのディレクトリ (例: ``svc``)
    packages: tuple[tuple[str, str], ...]  # (名前, 上げる版)

    def validate(self) -> UpdateJob:
        if not RUN_ID.match(self.run_id):
            raise InvalidJob(f"bad run_id: {self.run_id!r}")
        parts = PurePosixPath(self.project).parts
        if not PROJECT.match(self.project) or ".." in parts or self.project.startswith("/"):
            raise InvalidJob(f"bad project: {self.project!r}")
        if not self.packages:
            raise InvalidJob("no packages")
        for name, version in self.packages:
            if not NAME.match(name) or not VERSION.match(version):
                raise InvalidJob(f"bad package: {name!r}=={version!r}")
        return self


@dataclass(frozen=True)
class UpdateResult:
    run_id: str
    ok: bool  # 1 つでも上げられたら True (lock が入る)
    lock: str | None  # 更新後の uv.lock の中身
    applied: tuple[str, ...] = ()
    failed: tuple[tuple[str, str], ...] = ()  # (名前, uv の出力の末尾)
    uv_version: str = ""
    finished_at: str = ""
    error: str | None = None  # パッケージ以前の失敗 (読めない依頼・uv が無いなど)
    log: str = field(default="", repr=False)


# ── 対象のサービスと path 依存を写しから取り出す ─────────────────────────
def _path_sources(project_dir: Path) -> list[str]:
    """pyproject.toml の [tool.uv.sources] のうち path 指定のもの。"""
    pyproject = project_dir / "pyproject.toml"
    if not pyproject.is_file():
        return []
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    sources = ((data.get("tool") or {}).get("uv") or {}).get("sources") or {}
    out = []
    for spec in sources.values():
        for s in spec if isinstance(spec, list) else [spec]:
            if isinstance(s, dict) and isinstance(s.get("path"), str):
                out.append(s["path"])
    return out


def project_closure(root: Path, project: str) -> list[str]:
    """サービスと、そこから path 依存でたどれるディレクトリ (root からの相対パス)。root の外は拒否する。"""
    root = root.resolve()
    seen: list[str] = []
    queue = [project.rstrip("/")]
    while queue:
        rel = queue.pop(0)
        if rel in seen:
            continue
        d = (root / rel).resolve()
        if not d.is_relative_to(root) or d == root or not d.is_dir():
            raise InvalidJob(f"path dependency outside the repository: {rel}")
        seen.append(rel)
        for p in _path_sources(d):
            target = (d / p).resolve()
            if not target.is_relative_to(root):
                raise InvalidJob(f"path dependency outside the repository: {rel} -> {p}")
            queue.append(str(target.relative_to(root)))
    return seen


def write_job(in_dir: Path, job: UpdateJob, snapshot: Path) -> list[str]:
    """tree を書いてから依頼を書く。取り出したディレクトリを返す。"""
    job.validate()
    dirs = project_closure(snapshot, job.project)
    tree = in_dir / job.run_id / "tree"
    if tree.exists():
        shutil.rmtree(tree)
    for rel in dirs:
        shutil.copytree(snapshot / rel, tree / rel, symlinks=True, ignore=IGNORE)
    write_json(in_dir / f"{job.run_id}.json", {
        "format": FORMAT, "run_id": job.run_id, "project": job.project,
        "packages": [list(p) for p in job.packages],
    })
    return dirs


def _read(path: Path, limit: int) -> dict[str, Any]:
    if path.stat().st_size > limit:
        raise InvalidJob(f"{path.name} is larger than {limit} bytes")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise InvalidJob(f"{path.name}: not JSON ({e})") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise InvalidJob(f"{path.name}: unknown format")
    return data


def list_jobs(in_dir: Path) -> list[str]:
    if not in_dir.is_dir():
        return []
    files = [p for p in in_dir.glob("*.json") if RUN_ID.match(p.stem)]
    return [p.stem for p in sorted(files, key=lambda p: (p.stat().st_mtime, p.name))]


def read_job(in_dir: Path, run_id: str) -> UpdateJob:
    d = _read(in_dir / f"{run_id}.json", MAX_JOB_BYTES)
    if d.get("run_id") != run_id:
        raise InvalidJob(f"{run_id}: run_id does not match")
    try:
        packages = tuple((str(n), str(v)) for n, v in d["packages"])
        return UpdateJob(run_id, str(d["project"]), packages).validate()
    except (KeyError, TypeError, ValueError) as e:
        raise InvalidJob(f"{run_id}: {e}") from None


def remove_job(in_dir: Path, out_dir: Path, run_id: str) -> None:
    (in_dir / f"{run_id}.json").unlink(missing_ok=True)
    shutil.rmtree(in_dir / run_id, ignore_errors=True)
    (out_dir / f"{run_id}.json").unlink(missing_ok=True)


def write_result(out_dir: Path, r: UpdateResult) -> None:
    write_json(out_dir / f"{r.run_id}.json", {
        "format": FORMAT, "run_id": r.run_id, "ok": r.ok, "lock": r.lock, "applied": list(r.applied),
        "failed": [list(f) for f in r.failed], "uv_version": r.uv_version, "finished_at": r.finished_at,
        "error": r.error, "log": r.log[-20_000:],
    })


def read_result(out_dir: Path, run_id: str) -> UpdateResult | None:
    """まだ無ければ None。形が違えば InvalidJob (updater の出力は信頼しない)。"""
    path = out_dir / f"{run_id}.json"
    if not path.exists():
        return None
    d = _read(path, MAX_RESULT_BYTES)
    try:
        if d["run_id"] != run_id:
            raise InvalidJob(f"{run_id}: run_id does not match")
        lock = d.get("lock")
        if lock is not None and not isinstance(lock, str):
            raise InvalidJob(f"{run_id}: lock is not text")
        return UpdateResult(
            run_id, bool(d["ok"]), lock, tuple(str(a) for a in d.get("applied") or []),
            tuple((str(n), str(e)[:2000]) for n, e in d.get("failed") or []),
            str(d.get("uv_version") or "")[:100], str(d.get("finished_at") or "")[:40],
            str(d["error"])[:2000] if d.get("error") else None, str(d.get("log") or "")[-20_000:],
        )
    except (KeyError, TypeError, ValueError) as e:
        raise InvalidJob(f"{run_id}: {e}") from None
