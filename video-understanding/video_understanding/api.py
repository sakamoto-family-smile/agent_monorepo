"""CLI と MCP (PR2) が呼ぶ処理の本体。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import frames as fr
from .cache import Cache
from .config import Config
from .fetch import YdlFactory, _default_factory, fetch_youtube
from .source import Source, parse_source
from .transcript import Segment, format_segments, format_timestamp, parse_json3, parse_vtt

LANG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")
DESCRIPTION_MAX_CHARS = 1500
TRANSCRIPT_MAX_CHARS = 12000
UNTRUSTED_TAG = "untrusted_video_text"


class InputError(ValueError):
    """引数がおかしい。メッセージはそのまま利用者に見せる。"""


@dataclass(frozen=True)
class Transcript:
    source: str  # captions_manual / captions_auto
    lang: str
    segments: list[Segment]
    translated_from: str | None = None


@dataclass(frozen=True)
class Prepared:
    source: Source
    info: dict[str, Any]
    video: Path
    work_dir: Path
    meta: fr.VideoMeta
    transcript: Transcript | None = None
    transcript_note: str | None = None


@dataclass(frozen=True)
class OverviewResult:
    prepared: Prepared
    interval: float
    sheets: list[Path] = field(default_factory=list)


@dataclass(frozen=True)
class FramesResult:
    prepared: Prepared
    times: list[float]
    sheets: list[Path] = field(default_factory=list)


def _parse_caption(ext: str, body: str) -> list[Segment]:
    return parse_json3(json.loads(body)) if ext == "json3" else parse_vtt(body)


def prepare(
    raw_source: str, cfg: Config, lang: str = "ja", ydl_factory: YdlFactory = _default_factory
) -> Prepared:
    if not LANG_RE.match(lang):
        raise InputError(f"lang は ja / en のような言語コードで指定してください: {lang!r}")
    source = parse_source(raw_source, cfg.allowed_dirs)
    work_dir = Cache(cfg.cache_dir).dir_for(source.key)
    if source.kind == "local":
        assert source.path is not None
        meta = fr.probe(source.path)
        if meta.duration > cfg.max_duration_sec:
            raise InputError(
                f"動画が長すぎます ({meta.duration / 60:.0f} 分)。上限は {cfg.max_duration_sec / 60:.0f} 分です"
            )
        info = {"title": source.path.name, "duration": meta.duration, "path": str(source.path)}
        return Prepared(
            source,
            info,
            source.path,
            work_dir,
            meta,
            transcript_note="ローカルの動画には字幕がありません (文字起こしは未対応)",
        )
    assert source.url is not None
    fetched = fetch_youtube(source.url, work_dir, lang, cfg.max_duration_sec, ydl_factory)
    meta = fr.probe(fetched.video)
    track, body = fetched.caption, fetched.caption_body
    if track is None or body is None:
        note = fetched.caption_error or "この動画には字幕がありません (文字起こしは未対応)"
        return Prepared(source, fetched.info, fetched.video, work_dir, meta, transcript_note=note)
    transcript = Transcript(
        track.kind, track.lang, _parse_caption(track.ext, body), track.translated_from
    )
    return Prepared(source, fetched.info, fetched.video, work_dir, meta, transcript)


def overview(
    raw_source: str,
    cfg: Config,
    interval: float | None = None,
    lang: str = "ja",
    ydl_factory: YdlFactory = _default_factory,
) -> OverviewResult:
    prepared = prepare(raw_source, cfg, lang, ydl_factory)
    step = interval if interval is not None else fr.auto_interval(prepared.meta.duration)
    times = fr.sample_times(prepared.meta.duration, step)
    frames = fr.extract(prepared.video, times, prepared.work_dir / "frames")
    sheets = [
        fr.contact_sheet(group, prepared.work_dir / "sheets" / f"overview_i{step:g}_{n}.jpg")
        for n, group in enumerate(fr.chunk(frames), start=1)
    ]
    return OverviewResult(prepared, step, sheets)


def frames(
    raw_source: str,
    cfg: Config,
    start: float,
    end: float,
    fps: float = 10,
    crop: str | None = None,
    ydl_factory: YdlFactory = _default_factory,
) -> FramesResult:
    prepared = prepare(raw_source, cfg, ydl_factory=ydl_factory)
    crop_box = fr.Crop.parse(crop) if crop else None
    times = fr.range_times(start, end, fps, prepared.meta.duration)
    extracted = fr.extract(prepared.video, times, prepared.work_dir / "frames", crop_box)
    spec = f"range_{start:.3f}-{end:.3f}_f{fps:g}" + (f"_c{crop_box.slug()}" if crop_box else "")
    sheets = [
        fr.contact_sheet(group, prepared.work_dir / "sheets" / f"{spec}_{n}.jpg")
        for n, group in enumerate(fr.chunk(extracted), start=1)
    ]
    return FramesResult(prepared, [f.t for f in extracted], sheets)


# ---- 表示 --------------------------------------------------------------------------------


def wrap_untrusted(text: str, source: str) -> str:
    """動画側のテキスト (タイトル・説明・字幕) を、指示として読まないよう枠で囲む。"""
    escaped = re.sub(
        rf"</?\s*{UNTRUSTED_TAG}", lambda m: m.group(0).replace("<", "&lt;"), text, flags=re.I
    )
    return f'<{UNTRUSTED_TAG} source="{source}">\n{escaped}\n</{UNTRUSTED_TAG}>'


def _source_label(t: Transcript) -> str:
    kind = "手動字幕" if t.source == "captions_manual" else "自動字幕"
    if t.translated_from:
        return f"{kind} ({t.translated_from} から {t.lang} への YouTube の自動翻訳。誤りが多い可能性あり)"
    return f"{kind} ({t.lang})"


def _render_info(p: Prepared) -> list[str]:
    info = p.info
    lines = [
        f"動画: {info.get('webpage_url') or info.get('path')}",
        f"長さ: {format_timestamp(p.meta.duration)} ({p.meta.duration:.1f} 秒) / {p.meta.width}x{p.meta.height} / {p.meta.fps:.2f}fps",
    ]
    if info.get("channel") or info.get("uploader"):
        lines.append(
            wrap_untrusted(f"投稿者: {info.get('channel') or info.get('uploader')}", "channel")
        )
    lines.append(wrap_untrusted(f"タイトル: {info.get('title', '')}", "title"))
    if chapters := info.get("chapters"):
        body = "\n".join(
            f"[{format_timestamp(c['start_time'])}] {c.get('title', '')}" for c in chapters
        )
        lines.append(wrap_untrusted(body, "chapters"))
    if desc := (info.get("description") or "").strip():
        cut = desc[:DESCRIPTION_MAX_CHARS] + (
            "…(以下略)" if len(desc) > DESCRIPTION_MAX_CHARS else ""
        )
        lines.append(wrap_untrusted(cut, "description"))
    return lines


def _render_transcript(p: Prepared, max_chars: int) -> list[str]:
    if p.transcript is None:
        return [f"字幕: なし — {p.transcript_note}"]
    text, truncated = format_segments(p.transcript.segments, max_chars)
    lines = [f"字幕: {_source_label(p.transcript)}", wrap_untrusted(text, "captions")]
    if truncated:
        lines.append(f"(字幕は {max_chars} 文字で打ち切りました)")
    return lines


def render_overview(r: OverviewResult, max_chars: int = TRANSCRIPT_MAX_CHARS) -> str:
    lines = _render_info(r.prepared) + [""] + _render_transcript(r.prepared, max_chars) + [""]
    lines.append(f"一覧画像 ({r.interval:g} 秒間隔、各コマの左上が時刻):")
    lines += [f"  {s}" for s in r.sheets]
    return "\n".join(lines)


def render_frames(r: FramesResult) -> str:
    lines = [
        f"動画: {r.prepared.info.get('webpage_url') or r.prepared.info.get('path')}",
        f"コマ: {len(r.times)} 枚 ({r.times[0]:.3f}〜{r.times[-1]:.3f} 秒)"
        if r.times
        else "コマ: なし",
        "一覧画像 (各コマの左上が時刻):",
    ]
    lines += [f"  {s}" for s in r.sheets]
    return "\n".join(lines)
