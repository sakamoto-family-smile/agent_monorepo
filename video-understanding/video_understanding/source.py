"""入力 (YouTube の URL / ローカルの動画ファイル) の判定。受け付けるかどうかはここだけで決める。"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlsplit

YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com"})
SHORT_HOST = "youtu.be"
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
# /shorts/<id> /live/<id> /embed/<id>
PATH_ID_PREFIXES = ("shorts", "live", "embed")
HASH_CHUNK = 1 << 20
LOCAL_KEY_HEX = 16


class SourceError(ValueError):
    """受け付けない入力。メッセージはそのまま利用者に見せる。"""


@dataclass(frozen=True)
class Source:
    kind: Literal["youtube", "local"]
    key: str  # キャッシュのディレクトリ名 (yt-<id> / local-<sha256 先頭>)
    url: str | None = None
    path: Path | None = None


def _youtube_id(raw: str) -> str | None:
    """YouTube の動画 URL なら動画 ID を返す。YouTube 以外の URL なら None。"""
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or (host not in YOUTUBE_HOSTS and host != SHORT_HOST):
        return None
    segments = [s for s in parts.path.split("/") if s]
    if host == SHORT_HOST:
        candidate = segments[0] if len(segments) == 1 else ""
    elif segments == ["watch"]:
        candidate = parse_qs(parts.query).get("v", [""])[0]
    elif len(segments) == 2 and segments[0] in PATH_ID_PREFIXES:
        candidate = segments[1]
    else:
        candidate = ""
    if not VIDEO_ID_RE.match(candidate):
        raise SourceError(
            f"YouTube の動画 1 本の URL ではありません (プレイリストやチャンネルは不可): {raw}"
        )
    return candidate


def _sha256_prefix(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()[:LOCAL_KEY_HEX]


def _local(raw: str, allowed_dirs: Iterable[Path]) -> Source:
    roots = [d.expanduser().resolve() for d in allowed_dirs]
    if not roots:
        raise SourceError(
            "ローカルの動画は、VIDEO_UNDERSTANDING_ALLOWED_DIRS に入れたディレクトリの中だけ読めます (今は未設定)"
        )
    try:
        resolved = Path(raw).expanduser().resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as e:
        raise SourceError(f"ファイルが見つかりません: {raw}") from e
    if not resolved.is_file():
        raise SourceError(f"ファイルではありません: {raw}")
    if not any(resolved.is_relative_to(root) for root in roots):
        raise SourceError(f"許可されたディレクトリの外のファイルです: {raw}")
    return Source(kind="local", key=f"local-{_sha256_prefix(resolved)}", path=resolved)


def parse_source(raw: str, allowed_dirs: Iterable[Path]) -> Source:
    raw = raw.strip()
    if not raw:
        raise SourceError("動画の URL かファイルのパスを指定してください")
    if "://" in raw:
        video_id = _youtube_id(raw)
        if video_id is None:
            raise SourceError(f"YouTube 以外の URL は受け付けません: {raw}")
        return Source(
            kind="youtube", key=f"yt-{video_id}", url=f"https://www.youtube.com/watch?v={video_id}"
        )
    return _local(raw, allowed_dirs)
