"""yt-dlp で YouTube の動画の情報・字幕・低画質の動画を取ってくる。"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import imageio_ffmpeg

from .transcript import CaptionTrack, choose_caption

log = logging.getLogger(__name__)

# 短辺 480 以下 (横長 854x480 / 縦長 480x854)。height だけで絞ると縦長のショートが 240x426 まで落ちる
MAX_LONG_SIDE = 854
FORMAT = (
    f"bv*[height<={MAX_LONG_SIDE}][width<={MAX_LONG_SIDE}]+ba"
    f"/b[height<={MAX_LONG_SIDE}][width<={MAX_LONG_SIDE}]"
)
INFO_KEYS = (
    "id",
    "title",
    "channel",
    "uploader",
    "duration",
    "upload_date",
    "description",
    "chapters",
    "webpage_url",
    "language",
    "width",
    "height",
)
VIDEO_FILE = "video.mp4"
INFO_FILE = "info.json"


class FetchError(RuntimeError):
    """取得に失敗した。メッセージはそのまま利用者に見せる。"""


@dataclass(frozen=True)
class Fetched:
    info: dict[str, Any]
    video: Path
    caption: CaptionTrack | None
    caption_body: str | None  # 字幕の中身 (json3 / vtt のテキスト)。取れなければ None
    caption_error: str | None = None


class _Logger:
    """yt-dlp の出力を stdout に出さない (MCP の stdio を汚さない) ためのロガー。"""

    def debug(self, msg: str) -> None:
        log.debug(msg)

    def info(self, msg: str) -> None:
        log.debug(msg)

    def warning(self, msg: str) -> None:
        # JS 実行環境が無い等の注意は毎回出るので -v のときだけ見せる。必要な失敗は戻り値で伝える
        log.info(msg)

    def error(self, msg: str) -> None:
        log.error(msg)


YdlFactory = Callable[[Mapping[str, Any]], Any]


def _default_factory(opts: Mapping[str, Any]) -> Any:
    import yt_dlp

    return yt_dlp.YoutubeDL(dict(opts))


def _base_opts() -> dict[str, Any]:
    return {"quiet": True, "noprogress": True, "logger": _Logger(), "noplaylist": True}


def _summarize(info: Mapping[str, Any]) -> dict[str, Any]:
    out = {k: info[k] for k in INFO_KEYS if info.get(k) is not None}
    out["fetched_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    return out


def _download_errors() -> tuple[type[BaseException], ...]:
    try:
        from yt_dlp.utils import DownloadError, ExtractorError
    except ImportError:  # テストで yt-dlp を差し替えたとき
        return ()
    return (DownloadError, ExtractorError)


def _caption_meta_path(cache_dir: Path, lang: str) -> Path:
    return cache_dir / f"caption-{lang}.json"


def _load_cached(cache_dir: Path, lang: str) -> Fetched | None:
    """情報・動画・字幕 (この言語での選択結果) がそろっていれば、ネットワークに出ずに返す。"""
    info_path, video, meta_path = (
        cache_dir / INFO_FILE,
        cache_dir / VIDEO_FILE,
        _caption_meta_path(cache_dir, lang),
    )
    if not (info_path.exists() and video.exists() and meta_path.exists()):
        return None
    meta = json.loads(meta_path.read_text())
    if meta.get("track") is None:
        return Fetched(json.loads(info_path.read_text()), video, None, None)
    track = CaptionTrack(**meta["track"])
    body = (cache_dir / meta["body_file"]).read_text()
    return Fetched(json.loads(info_path.read_text()), video, track, body)


def _save_caption(
    cache_dir: Path, lang: str, caption: CaptionTrack | None, body: str | None
) -> None:
    meta: dict[str, Any] = {"track": None, "body_file": None}
    if caption is not None and body is not None:
        safe_lang = re.sub(r"[^A-Za-z0-9-]", "_", caption.lang)
        body_file = f"captions.{caption.kind}.{safe_lang}.{caption.ext}"
        (cache_dir / body_file).write_text(body)
        # URL は期限つきなので残さない
        meta = {"track": {**asdict(caption), "url": ""}, "body_file": body_file}
    _caption_meta_path(cache_dir, lang).write_text(json.dumps(meta, ensure_ascii=False))


def fetch_youtube(
    url: str,
    cache_dir: Path,
    lang: str,
    max_duration_sec: int,
    ydl_factory: YdlFactory = _default_factory,
) -> Fetched:
    """情報・字幕・動画を取得する。そろっていればキャッシュから返す。"""
    cached = _load_cached(cache_dir, lang)
    if cached is not None:
        return cached
    errors = _download_errors()
    try:
        with ydl_factory(_base_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
            _check_playable(info, max_duration_sec)
            caption = choose_caption(info, lang)
            body, caption_error = _read_caption(ydl, caption) if caption else (None, None)
        video = cache_dir / VIDEO_FILE
        if not video.exists():
            _download_video(url, cache_dir, ydl_factory)
    except errors as e:
        raise FetchError(f"YouTube から取得できませんでした: {e}") from e
    summary = _summarize(info)
    (cache_dir / INFO_FILE).write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    if caption_error is None:  # 取得に失敗したときは残さず、次の呼び出しで取り直す
        _save_caption(cache_dir, lang, caption, body)
    return Fetched(summary, video, caption, body, caption_error)


def _check_playable(info: Mapping[str, Any], max_duration_sec: int) -> None:
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
        raise FetchError("配信中・配信予定の動画には対応していません")
    duration = info.get("duration") or 0
    if duration > max_duration_sec:
        raise FetchError(
            f"動画が長すぎます ({duration / 60:.0f} 分)。上限は {max_duration_sec / 60:.0f} 分です "
            "(VIDEO_UNDERSTANDING_MAX_DURATION_SEC)"
        )


def _read_caption(ydl: Any, caption: CaptionTrack) -> tuple[str | None, str | None]:
    """字幕を読む。YouTube は字幕の取得を 429 で断ることがあるので、失敗しても動画の処理は続ける。"""
    try:
        return ydl.urlopen(caption.url).read().decode("utf-8"), None
    except Exception as e:  # noqa: BLE001 - 字幕が無くてもコマ画像は返したい
        log.warning("字幕を取得できませんでした: %s", e)
        return None, f"字幕を取得できませんでした ({e})"


def _download_video(url: str, cache_dir: Path, ydl_factory: YdlFactory) -> None:
    opts = {
        **_base_opts(),
        "format": FORMAT,
        "merge_output_format": "mp4",
        "outtmpl": str(cache_dir / "video.%(ext)s"),
        "ffmpeg_location": imageio_ffmpeg.get_ffmpeg_exe(),
    }
    with ydl_factory(opts) as ydl:
        ydl.download([url])
    if not (cache_dir / VIDEO_FILE).exists():
        raise FetchError("動画を保存できませんでした (mp4 にまとめられなかった)")
