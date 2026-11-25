"""音声の文字起こし (mlx-whisper, optional extra)。

音声は imageio-ffmpeg で 16kHz モノラルの float32 にして、配列のまま mlx_whisper に渡す
(mlx-whisper が PATH 上の ffmpeg を探さずに済む)。結果は動画ごとのキャッシュに残す。
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import imageio_ffmpeg

from .transcript import Segment

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
SILENCE_PEAK = (
    1e-3  # これより小さい音しか無ければ無音とみなす (無音を渡すと whisper は文を作り出す)
)
FFMPEG_AUDIO_TIMEOUT_SEC = 300
NO_AUDIO_MARKERS = ("matches no streams", "does not contain any stream")

TranscribeFn = Callable[..., dict[str, Any]]


class SpeechUnavailable(RuntimeError):
    """文字起こしができない (機能が入っていない・音声が無い)。メッセージはそのまま見せる。"""


def _default_transcribe() -> TranscribeFn:
    try:
        import mlx_whisper
    except ImportError as e:
        raise SpeechUnavailable(
            "文字起こしの機能が入っていません (`uv sync --extra whisper`、Apple Silicon の Mac のみ)"
        ) from e
    return mlx_whisper.transcribe


def load_audio(video: Path) -> Any:
    """動画の最初の音声トラックを 16kHz モノラルの float32 (numpy) で返す。"""
    import numpy as np  # mlx-whisper の依存。extra を入れていないときは呼ばれない

    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        str(video),
        "-map",
        "0:a:0",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-f",
        "f32le",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=FFMPEG_AUDIO_TIMEOUT_SEC)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        if any(m in err for m in NO_AUDIO_MARKERS):
            raise SpeechUnavailable("この動画には音声がありません")
        raise RuntimeError(f"音声を取り出せませんでした: {err[-300:]}")
    return np.frombuffer(proc.stdout, dtype=np.float32)


def whisper_lang(lang: str) -> str:
    """ja-JP → ja のように、whisper の言語コードにする。"""
    return lang.split("-")[0].lower()


def _cache_path(work_dir: Path, model: str, prompt: str, lang: str) -> Path:
    digest = hashlib.sha256(f"{model}\n{prompt}".encode()).hexdigest()[:12]
    return work_dir / f"whisper-{whisper_lang(lang)}-{digest}.json"


def _to_segments(result: dict[str, Any]) -> list[Segment]:
    out = []
    for s in result.get("segments") or []:
        text = str(s.get("text", "")).strip()
        if text:
            out.append(Segment(float(s["start"]), float(s["end"]), text))
    return out


def transcribe(
    video: Path,
    work_dir: Path,
    model: str,
    prompt: str,
    lang: str,
    transcribe_fn: TranscribeFn | None = None,
) -> list[Segment]:
    """文字起こしする。同じ動画・モデル・用語ヒント・言語ならキャッシュから返す。"""
    cached = _cache_path(work_dir, model, prompt, lang)
    if cached.exists():
        data = json.loads(cached.read_text())
        return [Segment(**s) for s in data["segments"]]
    fn = transcribe_fn or _default_transcribe()
    audio = load_audio(video)
    if audio.size == 0 or float(abs(audio).max()) < SILENCE_PEAK:
        raise SpeechUnavailable("この動画の音声は無音です")
    log.info("文字起こし: %s (%.0f 秒, %s)", video.name, audio.size / SAMPLE_RATE, model)
    result = fn(
        audio,
        path_or_hf_repo=model,
        language=whisper_lang(lang),
        initial_prompt=prompt or None,
        # 前の文に引きずられて同じ文を繰り返す失敗を避ける
        condition_on_previous_text=False,
    )
    segments = _to_segments(result)
    cached.write_text(
        json.dumps(
            {"model": model, "lang": lang, "segments": [asdict(s) for s in segments]},
            ensure_ascii=False,
            indent=1,
        )
    )
    return segments
