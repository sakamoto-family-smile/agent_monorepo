"""生データの保存 (FR-I01: 原文を改変せずに保存)。

``data/raw/<source>/dt=YYYY-MM-DD/<name>`` に書き、書き終えたら読み取り専用にする。
同名ファイルへの上書きは拒否する。保持期間を過ぎたものは prune で消す。
"""
from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from .timeutil import utc_now

READ_ONLY = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH


class RawStore:
    def __init__(self, raw_dir: Path) -> None:
        self._root = raw_dir

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

    def prune_dirs(self, source: str, prefix: str, keep: int) -> list[Path]:
        """``<source>/dt=*/<prefix>*`` を名前 (= 実行 ID) ごとにまとめ、新しい ``keep`` 実行分を残す。

        日付をまたいだ実行は複数の dt= に分かれるが、同じ名前なので 1 実行として数える。
        新しさは各実行の最終更新時刻で決める。
        """
        base = self._root / source
        if not base.exists():
            return []
        runs: dict[str, list[Path]] = {}
        for p in base.glob(f"dt=*/{prefix}*"):
            runs.setdefault(p.name, []).append(p)
        ordered = sorted(runs.values(), key=lambda ps: max(p.stat().st_mtime for p in ps))
        stale = ordered[:-keep] if keep > 0 else ordered
        removed = sorted(p for ps in stale for p in ps)
        for p in removed:
            _make_writable(p)
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
        return removed


def _make_writable(path: Path) -> None:
    targets = [path, *path.rglob("*")] if path.is_dir() else [path]
    for t in targets:
        t.chmod(t.stat().st_mode | stat.S_IWUSR)
