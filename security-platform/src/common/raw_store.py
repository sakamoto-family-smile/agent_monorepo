"""生データの保存 (FR-I01: 原文を改変せずに保存)。

``data/raw/<source>/dt=YYYY-MM-DD/<name>`` に書き、書き終えたら読み取り専用にする。
同名ファイルへの上書きは拒否する。保持期間を過ぎたものは prune で消す。
大きな書き込みの前には ensure_free_space で空き容量を確かめる (ノート PC のディスクを埋めない)。
"""
from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Container, Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import BinaryIO

from .timeutil import utc_now

READ_ONLY = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH


class DiskFull(RuntimeError):
    pass


class RawStore:
    def __init__(self, raw_dir: Path, *, min_free_bytes: int = 0) -> None:
        self._root = raw_dir
        self._min_free = min_free_bytes

    def ensure_free_space(self, need_bytes: int = 0) -> None:
        """空きが ``min_free_bytes + need_bytes`` を下回っていたら DiskFull。"""
        if self._min_free <= 0:
            return
        self._root.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(self._root).free
        if free < self._min_free + need_bytes:
            raise DiskFull(
                f"free space {free / 1e9:.1f} GB < required {(self._min_free + need_bytes) / 1e9:.1f} GB "
                f"on {self._root}"
            )

    def path_for(self, source: str, name: str, day: str | None = None) -> Path:
        day = day or utc_now().strftime("%Y-%m-%d")
        return self._root / source / f"dt={day}" / name

    def relative(self, path: Path) -> str:
        return str(path.relative_to(self._root.parent))

    def write_bytes(self, source: str, name: str, data: bytes) -> Path:
        with self.open_new(source, name) as (f, path):
            f.write(data)
        return path

    @contextmanager
    def open_new(self, source: str, name: str) -> Iterator[tuple[BinaryIO, Path]]:
        """一時ファイルに書いてから rename し、読み取り専用にする。"""
        path = self.path_for(source, name)
        if path.exists():
            raise FileExistsError(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        try:
            with tmp.open("wb") as f:
                yield f, path
            os.replace(tmp, path)
            os.chmod(path, READ_ONLY)
        finally:
            if tmp.exists():
                tmp.unlink()

    def prune_dirs(
        self, source: str, prefix: str, keep: int,
        *, complete: Container[str] | None = None, protect: Container[str] = (),
    ) -> list[Path]:
        """``<source>/dt=*/<prefix>*`` を名前 (= 実行 ID) ごとにまとめ、新しい ``keep`` 実行分を残す。

        日付をまたいだ実行は複数の dt= に分かれるが、同じ名前なので 1 実行として数える。
        新しさは各実行の最終更新時刻で決める。``complete`` を渡すと、そこに名前が無い実行
        (失敗して途中までしか無いもの) は世代として数えずに消す。``protect`` の名前は消さない。
        """
        base = self._root / source
        if not base.exists():
            return []
        runs: dict[str, list[Path]] = {}
        for p in base.glob(f"dt=*/{prefix}*"):
            runs.setdefault(p.name, []).append(p)
        ordered = sorted(runs.items(), key=lambda kv: max(p.stat().st_mtime for p in kv[1]))
        ordered = [(n, ps) for n, ps in ordered if n not in protect]
        incomplete = [(n, ps) for n, ps in ordered if complete is not None and n not in complete]
        done = [(n, ps) for n, ps in ordered if complete is None or n in complete]
        stale = incomplete + (done[:-keep] if keep > 0 else done)
        removed = sorted(p for _n, ps in stale for p in ps)
        for p in removed:
            _remove(p)
        return removed

    def prune_older_than(self, source: str, age: timedelta, *, prefixes: tuple[str, ...] = ("",)) -> list[Path]:
        """``<source>/dt=*/`` のうち日付が ``age`` より古いものから、名前が ``prefixes`` で始まるものを消す。

        ``.part`` (書き込み途中で落ちた一時ファイル) は日付に関係なく 1 日経てば消す。
        """
        base = self._root / source
        if not base.exists():
            return []
        now = utc_now()
        cutoff = (now - age).strftime("%Y-%m-%d")
        part_cutoff = (now - timedelta(days=1)).timestamp()
        removed: list[Path] = []
        for day_dir in sorted(base.glob("dt=*")):
            old = day_dir.name.removeprefix("dt=") < cutoff
            for p in sorted(day_dir.iterdir()):
                stale_part = p.name.endswith(".part") and p.stat().st_mtime < part_cutoff
                if stale_part or (old and p.name.startswith(prefixes)):
                    _remove(p)
                    removed.append(p)
            if not any(day_dir.iterdir()):
                day_dir.rmdir()
        return removed


def _remove(p: Path) -> None:
    _make_writable(p)
    if p.is_dir():
        shutil.rmtree(p)
    else:
        p.unlink()


def _make_writable(path: Path) -> None:
    targets = [path, *path.rglob("*")] if path.is_dir() else [path]
    for t in targets:
        t.chmod(t.stat().st_mode | stat.S_IWUSR)
