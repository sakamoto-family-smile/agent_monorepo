"""動画ごとのキャッシュディレクトリ。"""

from __future__ import annotations

import re
import time
from pathlib import Path

KEY_RE = re.compile(r"^(yt-[A-Za-z0-9_-]{11}|local-[0-9a-f]{16})$")
LAST_USED = ".last_used"


class Cache:
    def __init__(self, root: Path):
        self.root = root

    def dir_for(self, key: str) -> Path:
        """キーのディレクトリを (無ければ作って) 返し、最終利用時刻を更新する。"""
        if not KEY_RE.match(key):
            raise ValueError(f"キャッシュのキーとして不正です: {key!r}")
        d = self.root / key
        d.mkdir(parents=True, exist_ok=True)
        (d / LAST_USED).write_text(str(int(time.time())))
        return d
