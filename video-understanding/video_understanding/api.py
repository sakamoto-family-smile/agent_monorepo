"""CLI と MCP (PR2) が呼ぶ処理の本体。"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import frames as fr
from . import speech
from .cache import Cache
from .config import Config
from .fetch import YdlFactory, fetch_youtube
from .source import Source, parse_source
from .transcript import Segment, format_segments, format_timestamp, parse_json3, parse_vtt

log = logging.getLogger(__name__)

LANG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")
DESCRIPTION_MAX_CHARS = 1500
TRANSCRIPT_MAX_CHARS = 12000
FULL_TRANSCRIPT_MAX_CHARS = 100000
UNTRUSTED_TAG = "untrusted_video_text"


class InputError(ValueError):
    """引数がおかしい。メッセージはそのまま利用者に見せる。"""


@dataclass(frozen=True)
class Transcript:
    source: str  # captions_manual / captions_auto / whisper:<model>
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
    raw_source: str, cfg: Config, lang: str = "ja", ydl_factory: YdlFactory | None = None
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
            transcript_note="ローカルの動画には字幕がありません",
        )
    assert source.url is not None
    fetched = fetch_youtube(source.url, work_dir, lang, cfg.max_duration_sec, ydl_factory)
    meta = fr.probe(fetched.video)
    track, body = fetched.caption, fetched.caption_body
    if track is None or body is None:
        note = fetched.caption_error or "この動画には字幕がありません"
        return Prepared(source, fetched.info, fetched.video, work_dir, meta, transcript_note=note)
    transcript = Transcript(
        track.kind, track.lang, _parse_caption(track.ext, body), track.translated_from
    )
    return Prepared(source, fetched.info, fetched.video, work_dir, meta, transcript)


def _join(*notes: str | None) -> str:
    return "。".join(n for n in notes if n)


def with_speech(
    p: Prepared,
    cfg: Config,
    lang: str,
    force_whisper: bool = False,
    transcribe_fn: speech.TranscribeFn | None = None,
) -> Prepared:
    """字幕が無ければ (force_whisper なら字幕があっても) 音声を文字起こしする。

    文字起こしができないときは、字幕 (あれば) のまま理由を note に足して返す。
    """
    if p.transcript is not None and not force_whisper:
        return p
    try:
        segments = speech.transcribe(
            p.video, p.work_dir, cfg.whisper_model, cfg.whisper_prompt, lang, transcribe_fn
        )
    except speech.SpeechUnavailable as e:
        return dataclasses.replace(p, transcript_note=_join(p.transcript_note, str(e)))
    except Exception as e:  # noqa: BLE001 - 文字起こしが失敗してもコマ画像は返したい
        log.exception("文字起こしに失敗しました")
        note = _join(p.transcript_note, f"文字起こしに失敗しました ({e})")
        return dataclasses.replace(p, transcript_note=note)
    if not segments:
        note = _join(p.transcript_note, "文字起こしで言葉が見つかりませんでした")
        return dataclasses.replace(p, transcript_note=note)
    t = Transcript(f"whisper:{cfg.whisper_model}", speech.whisper_lang(lang), segments)
    return dataclasses.replace(p, transcript=t, transcript_note=None)


def overview(
    raw_source: str,
    cfg: Config,
    interval: float | None = None,
    lang: str = "ja",
    ydl_factory: YdlFactory | None = None,
    transcribe_fn: speech.TranscribeFn | None = None,
) -> OverviewResult:
    prepared = with_speech(
        prepare(raw_source, cfg, lang, ydl_factory), cfg, lang, transcribe_fn=transcribe_fn
    )
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
    ydl_factory: YdlFactory | None = None,
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


def transcript(
    raw_source: str,
    cfg: Config,
    lang: str = "ja",
    force_whisper: bool = False,
    ydl_factory: YdlFactory | None = None,
    transcribe_fn: speech.TranscribeFn | None = None,
) -> Prepared:
    """字幕か文字起こしだけが欲しいとき。コマは抜かない。"""
    prepared = prepare(raw_source, cfg, lang, ydl_factory)
    return with_speech(prepared, cfg, lang, force_whisper, transcribe_fn)


# ---- 表示 --------------------------------------------------------------------------------


def wrap_untrusted(text: str, source: str) -> str:
    """動画側のテキスト (タイトル・説明・字幕) を、指示として読まないよう枠で囲む。"""
    escaped = re.sub(
        rf"</?\s*{UNTRUSTED_TAG}", lambda m: m.group(0).replace("<", "&lt;"), text, flags=re.I
    )
    return f'<{UNTRUSTED_TAG} source="{source}">\n{escaped}\n</{UNTRUSTED_TAG}>'


def _source_label(t: Transcript) -> str:
    if t.source.startswith("whisper:"):
        model = t.source.removeprefix("whisper:")
        return (
            f"文字起こし (mlx-whisper {model}, {t.lang}。固有名詞や専門用語は誤りがある可能性あり)"
        )
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
    kind = "transcription" if p.transcript.source.startswith("whisper:") else "captions"
    lines = [f"字幕: {_source_label(p.transcript)}", wrap_untrusted(text, kind)]
    if truncated:
        lines.append(f"(字幕は {max_chars} 文字で打ち切りました)")
    if p.transcript_note:
        lines.append(f"(注: {p.transcript_note})")
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


def render_transcript(p: Prepared, max_chars: int = FULL_TRANSCRIPT_MAX_CHARS) -> str:
    head = f"動画: {p.info.get('webpage_url') or p.info.get('path')}"
    return "\n".join([head, *_render_transcript(p, max_chars)])
