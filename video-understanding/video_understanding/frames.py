"""コマ抜き (ffmpeg) と、時刻入りの一覧画像 (Pillow)。"""

from __future__ import annotations

import math
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

MAX_SHEET_PX = 1568  # Claude が縮小せずに見られる長辺
FRAMES_PER_SHEET = 20
OVERVIEW_MAX_FRAMES = 2 * FRAMES_PER_SHEET
RANGE_MAX_FRAMES = 30
RANGE_MAX_FPS = 30
INTERVAL_STEPS = (0.25, 0.5, 1, 2, 3, 5, 10, 15, 20, 30, 60, 120, 300, 600)
JPEG_QUALITY = 85
FFMPEG_TIMEOUT_SEC = 60
LABEL_PAD = 3
NO_FRAME_MARKER = "Nothing was written into output file"


class FramesError(ValueError):
    """コマの指定がおかしい。メッセージはそのまま利用者に見せる。"""


@dataclass(frozen=True)
class VideoMeta:
    duration: float
    fps: float
    width: int
    height: int


@dataclass(frozen=True)
class Crop:
    """比率 (0〜1) で表した切り出し範囲。"""

    x: float
    y: float
    w: float
    h: float

    @classmethod
    def parse(cls, raw: str) -> Crop:
        try:
            x, y, w, h = (float(v) for v in raw.split(","))
        except ValueError as e:
            raise FramesError(f"crop は x,y,w,h を 0〜1 の比率で指定してください: {raw!r}") from e
        if min(x, y) < 0 or min(w, h) <= 0 or x + w > 1 + 1e-9 or y + h > 1 + 1e-9:
            raise FramesError(f"crop が画面からはみ出しています: {raw!r}")
        return cls(x, y, w, h)

    def ffmpeg_filter(self) -> str:
        return f"crop=iw*{self.w}:ih*{self.h}:iw*{self.x}:ih*{self.y}"

    def slug(self) -> str:
        return "_".join(f"{v:g}" for v in (self.x, self.y, self.w, self.h))


@dataclass(frozen=True)
class Frame:
    t: float
    path: Path


def probe(path: Path) -> VideoMeta:
    """長さ・fps・大きさを読む (ffprobe は imageio-ffmpeg に入っていないので、読み込みの先頭だけ使う)。"""
    reader = imageio_ffmpeg.read_frames(str(path))
    try:
        meta = next(reader)
    finally:
        reader.close()
    width, height = meta["size"]
    if meta.get("rotate") in (90, 270, -90):
        width, height = height, width
    return VideoMeta(float(meta["duration"]), float(meta["fps"]), int(width), int(height))


def auto_interval(duration: float, max_frames: int = OVERVIEW_MAX_FRAMES) -> float:
    """全体を max_frames コマ以内に収める、きりのよい間隔 (秒)。"""
    for step in INTERVAL_STEPS:
        if math.ceil(duration / step) <= max_frames:
            return float(step)
    return float(math.ceil(duration / max_frames))


def sample_times(
    duration: float, interval: float, max_frames: int = OVERVIEW_MAX_FRAMES
) -> list[float]:
    if interval <= 0:
        raise FramesError("間隔は 0 より大きくしてください")
    count = max(1, math.ceil(duration / interval))
    if count > max_frames:
        raise FramesError(
            f"{interval:g} 秒間隔だと {count} コマになり、上限 {max_frames} を超えます。間隔を広げてください"
        )
    return [round(k * interval, 3) for k in range(count)]


def range_times(start: float, end: float, fps: float, duration: float) -> list[float]:
    if not 0 < fps <= RANGE_MAX_FPS:
        raise FramesError(f"fps は 0 より大きく {RANGE_MAX_FPS} 以下にしてください: {fps:g}")
    if not 0 <= start < end:
        raise FramesError(f"区間は 0 <= start < end にしてください: {start:g}〜{end:g}")
    if start >= duration:
        raise FramesError(f"start が動画の長さ ({duration:.2f} 秒) を超えています")
    end = min(end, duration)
    step = 1 / fps
    count = math.floor((end - start) / step + 1e-6) + 1
    if count > RANGE_MAX_FRAMES:
        raise FramesError(
            f"{start:g}〜{end:g} 秒を {fps:g}fps で取ると {count} コマになり、上限 {RANGE_MAX_FRAMES} を超えます。"
            "区間を狭めるか fps を下げてください"
        )
    return [round(start + k * step, 3) for k in range(count)]


def extract(
    video: Path, times: Sequence[float], out_dir: Path, crop: Crop | None = None
) -> list[Frame]:
    """指定した時刻のコマを JPEG で書き出す。同じものが既にあれば使い回す。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    suffix = f"_c{crop.slug()}" if crop else ""
    frames = []
    for t in times:
        dest = out_dir / f"{t:09.3f}{suffix}.jpg"
        if not dest.exists():
            cmd = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{t:.3f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-q:v",
                "3",
            ]
            if crop:
                cmd += ["-vf", crop.ffmpeg_filter()]
            tmp = dest.with_name(dest.stem + ".part.jpg")
            proc = subprocess.run(
                [*cmd, "-y", str(tmp)], capture_output=True, timeout=FFMPEG_TIMEOUT_SEC
            )
            if not tmp.exists():
                err = proc.stderr.decode("utf-8", "replace")
                # 終端付近で読めるコマが無かった (音声のほうが映像より長い動画で起きる)
                if proc.returncode == 0 or NO_FRAME_MARKER in err:
                    continue
                raise FramesError(f"{t:.3f} 秒のコマを取り出せませんでした: {err.strip()[-300:]}")
            tmp.rename(dest)
        frames.append(Frame(t, dest))
    return frames


def _grid(n: int, cell_aspect: float) -> tuple[int, int]:
    """一覧画像がなるべく正方形に近くなる列数・行数。cell_aspect = 幅 / 高さ。"""
    cols = max(1, min(n, round(math.sqrt(n / cell_aspect))))
    return cols, math.ceil(n / cols)


def _label(t: float) -> str:
    m, s = divmod(t, 60)
    return f"{int(m)}:{s:05.2f}" if m else f"{s:.2f}s"


def contact_sheet(frames: Sequence[Frame], out_path: Path, max_px: int = MAX_SHEET_PX) -> Path:
    """コマを格子に並べ、左上に時刻を入れた 1 枚の画像にする (長辺 max_px 以下)。"""
    if not frames:
        raise FramesError("並べるコマがありません")
    if len(frames) > FRAMES_PER_SHEET:
        raise FramesError(f"1 枚に並べられるのは {FRAMES_PER_SHEET} コマまでです")
    images = [Image.open(f.path).convert("RGB") for f in frames]
    fw, fh = images[0].size
    cols, rows = _grid(len(images), fw / fh)
    scale = min(1.0, max_px / (cols * fw), max_px / (rows * fh))
    cw, ch = max(1, int(fw * scale)), max(1, int(fh * scale))
    sheet = Image.new("RGB", (cols * cw, rows * ch), "black")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=max(10, ch // 12))
    for i, (frame, img) in enumerate(zip(frames, images, strict=True)):
        x, y = (i % cols) * cw, (i // cols) * ch
        sheet.paste(img.resize((cw, ch)), (x, y))
        text = _label(frame.t)
        box = draw.textbbox((x + LABEL_PAD, y + LABEL_PAD), text, font=font)
        draw.rectangle(
            (box[0] - LABEL_PAD, box[1] - LABEL_PAD, box[2] + LABEL_PAD, box[3] + LABEL_PAD),
            fill="black",
        )
        draw.text((x + LABEL_PAD, y + LABEL_PAD), text, fill="yellow", font=font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, "JPEG", quality=JPEG_QUALITY)
    return out_path


def chunk(frames: Sequence[Frame], size: int = FRAMES_PER_SHEET) -> list[list[Frame]]:
    return [list(frames[i : i + size]) for i in range(0, len(frames), size)]
