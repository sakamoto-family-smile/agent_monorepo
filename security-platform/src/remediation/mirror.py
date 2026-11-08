"""origin/main の写し (data/remediation/main)。

detection は手元の作業コピーではなくこの写しを照合する。手元がブランチや古い main のままでも、
照合が main (= 本番。main へのマージで自動デプロイされる) とずれないようにするため。
自動改修の PR がマージされたら、次の写しの更新と照合で Finding が閉じる。

    data/remediation/snapshots/<sha>/   コミットの中身 (GitHub の tarball を展開したもの。.git は無い)
    data/remediation/main -> snapshots/<sha>   今の main (symlink の付け替えで切り替える)

symlink の付け替えは 1 回の rename なので、読み手 (detection) が書きかけの写しを見ることはない。
古い写しは KEEP 世代だけ残して消す (照合中に前の写しを読んでいても消えないように 1 つ前は残す)。
tarball にはコミットされたファイルしか入らないので、手元の .env などの秘密情報は写しに入らない。
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .github import GitHub

logger = logging.getLogger(__name__)

KEEP = 2
SHA = re.compile(r"^[0-9a-f]{40}$")
# 写しに必ずあるはずのファイル (無ければ壊れた tarball とみなして切り替えない)
REQUIRED = "security-platform/config/services.yaml"


class MirrorError(RuntimeError):
    pass


def current_sha(root: Path) -> str | None:
    """今の写しのコミット (まだ無ければ None)。root は data/remediation。"""
    try:
        target = os.readlink(root / "main")
    except OSError:
        return None
    sha = PurePosixPath(target).name
    return sha if SHA.match(sha) and (root / "snapshots" / sha).is_dir() else None


@dataclass(frozen=True)
class SyncResult:
    sha: str
    changed: bool
    previous: str | None


class MainMirror:
    def __init__(self, github: GitHub, root: Path, branch: str = "main", max_bytes: int = 200 * 2**20) -> None:
        self.github = github
        self.root = root
        self.branch = branch
        self.max_bytes = max_bytes

    @property
    def link(self) -> Path:
        return self.root / "main"

    @property
    def snapshots(self) -> Path:
        return self.root / "snapshots"

    def current(self) -> str | None:
        return current_sha(self.root)

    def sync(self) -> SyncResult:
        sha = self.github.head_sha(self.branch)
        previous = self.current()
        if sha == previous:
            return SyncResult(sha, False, previous)
        self.snapshots.mkdir(parents=True, exist_ok=True)
        dest = self.snapshots / sha
        if not dest.is_dir():
            self._fetch(sha, dest)
        self._switch(sha)
        self._prune(keep={sha, previous})
        logger.info("main mirror: %s -> %s", (previous or "-")[:12], sha[:12])
        return SyncResult(sha, True, previous)

    # ── 取得・展開 ───────────────────────────────────────────────────────
    def _fetch(self, sha: str, dest: Path) -> None:
        work = Path(tempfile.mkdtemp(prefix=f".tmp-{sha[:12]}-", dir=self.snapshots))
        try:
            archive = work / "src.tar.gz"
            self._download(sha, archive)
            tree = work / "tree"
            extract(archive, tree)
            if not (tree / REQUIRED).is_file():
                raise MirrorError(f"{sha[:12]}: tarball に {REQUIRED} がありません")
            os.replace(tree, dest)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _download(self, sha: str, path: Path) -> None:
        size = 0
        with self.github.tarball(sha) as resp, path.open("wb") as f:
            for chunk in resp.iter_bytes():
                size += len(chunk)
                if size > self.max_bytes:
                    raise MirrorError(f"{sha[:12]}: tarball が {self.max_bytes // 2**20} MB を超えました")
                f.write(chunk)

    def _switch(self, sha: str) -> None:
        tmp = self.root / f".main-{sha[:12]}"
        tmp.unlink(missing_ok=True)
        tmp.symlink_to(Path("snapshots") / sha)  # 相対リンク (コンテナとホストでマウント先が違っても辿れる)
        os.replace(tmp, self.link)

    def _prune(self, keep: set[str | None]) -> None:
        dirs = sorted((p for p in self.snapshots.iterdir() if p.is_dir() and SHA.match(p.name)),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        kept = 0
        for p in dirs:
            if p.name in keep and kept < KEEP:
                kept += 1
                continue
            shutil.rmtree(p, ignore_errors=True)
        for p in self.snapshots.glob(".tmp-*"):  # 前回途中で落ちたときの残り
            shutil.rmtree(p, ignore_errors=True)


def _strip_top(name: str) -> str | None:
    """``<repo>-<sha>/path`` の先頭の 1 階層を取る。先頭のディレクトリ自身は None。"""
    parts = PurePosixPath(name).parts
    return str(PurePosixPath(*parts[1:])) if len(parts) > 1 else None


def extract(archive: Path, dest: Path) -> None:
    """GitHub の tarball を展開する (先頭のディレクトリを外す)。

    tarfile の ``data`` フィルタで、絶対パス・dest の外を指すパスとリンク・デバイスファイルを拒否する。
    """
    dest.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as tar:
        members = []
        for m in tar.getmembers():
            name = _strip_top(m.name)
            if name is None:
                continue
            m.name = name
            if m.islnk():  # ハードリンクの参照先も同じく先頭を外す
                m.linkname = _strip_top(m.linkname) or ""
            members.append(m)
        tar.extractall(dest, members=members, filter="data")
