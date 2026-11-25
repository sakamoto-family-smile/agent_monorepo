"""動画ごとのキャッシュディレクトリ。"""

from __future__ import annotations

import re
import shutil
import time
from dataclasses import dataclass
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


# 期限が来たら消すもの (大きくて、取り直せるもの)。情報・字幕・文字起こしは小さいので残す
EXPIRING_DIRS = ("frames", "sheets")
EXPIRING_FILE_PREFIX = "video."  # video.mp4 と、yt-dlp の途中のファイル (video.f399.mp4.part など)
SECONDS_PER_DAY = 86400


@dataclass(frozen=True)
class GcResult:
    expired: list[Path]  # 中身を消した (dry_run なら消す予定の) キャッシュディレクトリ
    freed_bytes: int


def _last_used(d: Path) -> float:
    marker = d / LAST_USED
    try:
        return float(marker.read_text().strip())
    except (OSError, ValueError):
        return d.stat().st_mtime


def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink())


def _expiring(d: Path) -> list[Path]:
    targets = [d / name for name in EXPIRING_DIRS if (d / name).is_dir()]
    targets += [f for f in d.iterdir() if f.is_file() and f.name.startswith(EXPIRING_FILE_PREFIX)]
    return [t for t in targets if not t.is_symlink()]


def gc(root: Path, ttl_days: int, now: float | None = None, dry_run: bool = False) -> GcResult:
    """最終利用から ttl_days を過ぎた動画の、動画本体とコマ・一覧画像を消す。"""
    now = time.time() if now is None else now
    cutoff = now - ttl_days * SECONDS_PER_DAY
    expired: list[Path] = []
    freed = 0
    if not root.is_dir():
        return GcResult(expired, freed)
    for d in sorted(root.iterdir()):
        # キャッシュが作ったディレクトリだけを見る (他のものが置かれていても触らない)
        if d.is_symlink() or not d.is_dir() or not KEY_RE.match(d.name):
            continue
        if _last_used(d) >= cutoff:
            continue
        targets = _expiring(d)
        if not targets:
            continue
        expired.append(d)
        for t in targets:
            freed += _size(t)
            if dry_run:
                continue
            if t.is_dir():
                shutil.rmtree(t)
            else:
                t.unlink()
    return GcResult(expired, freed)
