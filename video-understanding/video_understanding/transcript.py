"""字幕 (json3 / vtt) の読み取りと、時刻つきテキストへの正規化。"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

CaptionKind = Literal["captions_manual", "captions_auto"]
ORIG_SUFFIX = "-orig"
VTT_TIME_RE = re.compile(
    r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})\s+-->\s+(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})"
)
VTT_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class CaptionTrack:
    kind: CaptionKind
    lang: str
    ext: str
    url: str
    translated_from: str | None = None  # 自動字幕を YouTube が翻訳したもののとき、元の言語


def _pick_format(entries: Iterable[Mapping[str, Any]]) -> tuple[str, str] | None:
    by_ext = {e.get("ext"): e.get("url") for e in entries if e.get("url")}
    for ext in ("json3", "vtt"):
        if by_ext.get(ext):
            return ext, by_ext[ext]
    return None


def choose_caption(info: Mapping[str, Any], lang: str) -> CaptionTrack | None:
    """字幕を 1 本選ぶ。

    手動字幕 (希望の言語 > その他) > 自動字幕 (希望の言語の元の字幕 > 希望の言語への翻訳 > 他の言語の元の字幕)。
    YouTube が話し言葉の言語を取り違えることがあるので、翻訳かどうかを translated_from に残す。
    """
    manual: Mapping[str, Any] = info.get("subtitles") or {}
    auto: Mapping[str, Any] = info.get("automatic_captions") or {}
    manual_keys = [k for k in manual if k == lang or k.startswith(lang + "-")]
    manual_keys += [k for k in manual if k not in manual_keys and k != "live_chat"]
    for key in manual_keys:
        picked = _pick_format(manual[key])
        if picked:
            return CaptionTrack("captions_manual", key, *picked)

    origs = [k.removesuffix(ORIG_SUFFIX) for k in auto if k.endswith(ORIG_SUFFIX)]
    orig_lang = origs[0] if origs else None
    auto_order: list[tuple[str, str, str | None]] = []  # (key, 言語, 翻訳元)
    if lang in origs:
        auto_order.append((lang + ORIG_SUFFIX, lang, None))
    if lang in auto and lang not in origs:
        auto_order.append((lang, lang, orig_lang))
    auto_order += [(o + ORIG_SUFFIX, o, None) for o in origs if o != lang]
    for key, track_lang, translated_from in auto_order:
        picked = _pick_format(auto[key])
        if picked:
            return CaptionTrack(
                "captions_auto", track_lang, *picked, translated_from=translated_from
            )
    return None


def _dedupe(segments: Iterable[Segment]) -> list[Segment]:
    """自動字幕で同じ文が続けて出るものを 1 つにまとめる (後ろの end まで伸ばす)。"""
    out: list[Segment] = []
    for s in segments:
        if out and out[-1].text == s.text:
            out[-1] = Segment(out[-1].start, max(out[-1].end, s.end), s.text)
        else:
            out.append(s)
    return out


def parse_json3(data: Mapping[str, Any]) -> list[Segment]:
    segments = []
    for ev in data.get("events") or []:
        text = (
            "".join(seg.get("utf8", "") for seg in ev.get("segs") or []).replace("\n", " ").strip()
        )
        if not text or "tStartMs" not in ev:
            continue
        start = ev["tStartMs"] / 1000
        segments.append(Segment(start, start + ev.get("dDurationMs", 0) / 1000, text))
    return _dedupe(segments)


def _vtt_seconds(h: str | None, m: str, s: str, ms: str) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_vtt(text: str) -> list[Segment]:
    """WebVTT を読む。自動字幕の「前の行を残して 1 行ずつ増える」形は、新しく出た行だけ残す。"""
    segments: list[Segment] = []
    seen_lines: set[str] = set()
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = block.strip().split("\n")
        idx = next((i for i, line in enumerate(lines) if VTT_TIME_RE.search(line)), None)
        if idx is None:
            continue
        g = VTT_TIME_RE.search(lines[idx]).groups()
        start, end = _vtt_seconds(*g[:4]), _vtt_seconds(*g[4:])
        new_lines = []
        for line in lines[idx + 1 :]:
            clean = VTT_TAG_RE.sub("", line).strip()
            if clean and clean not in seen_lines:
                new_lines.append(clean)
                seen_lines.add(clean)
        if new_lines:
            segments.append(Segment(start, end, " ".join(new_lines)))
    return _dedupe(segments)


def format_timestamp(sec: float) -> str:
    total = int(sec)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def format_segments(segments: Iterable[Segment], max_chars: int) -> tuple[str, bool]:
    """ "[mm:ss] 文" の行にする。max_chars を超えたら打ち切り、打ち切ったかどうかも返す。"""
    lines: list[str] = []
    used = 0
    for s in segments:
        line = f"[{format_timestamp(s.start)}] {s.text}"
        if used + len(line) + 1 > max_chars:
            return "\n".join(lines), True
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines), False
