"""1 つの SQLite / DuckDB ファイルに書き込むプロセスを 1 つに保つためのロック。

``data/.locks/<name>.lock`` を flock する。取れなければ待たずに WriterBusy を投げる。
flock は同じカーネルの中でしか効かない。Docker Desktop では VM の中 (compose のサービスと
``docker compose run``) どうしは排他されるが、ホストの macOS のプロセスとは排他されない。
そのため書き込みを伴うコマンドは Makefile からもコンテナ経由で実行する。
"""
from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class WriterBusy(RuntimeError):
    pass


@contextmanager
def writer_lock(root: Path, name: str) -> Iterator[None]:
    lock_dir = root / ".locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_dir / f"{name}.lock", os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise WriterBusy(f"another process is writing {name} (lock: {lock_dir / name}.lock)") from e
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
