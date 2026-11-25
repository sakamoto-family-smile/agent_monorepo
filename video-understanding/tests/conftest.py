import subprocess
from pathlib import Path

import imageio_ffmpeg
import pytest

from video_understanding.config import Config


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory) -> Path:
    """ffmpeg の testsrc で作る 3 秒・10fps・160x120 の動画。"""
    out = tmp_path_factory.mktemp("media") / "sample.mp4"
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=3:size=160x120:rate=10",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(out),
        ],
        check=True,
    )
    return out


@pytest.fixture
def cfg(tmp_path, sample_video) -> Config:
    return Config(
        cache_dir=tmp_path / "cache",
        allowed_dirs=(sample_video.parent,),
        video_ttl_days=14,
        max_duration_sec=1800,
    )


def _make_media(out: Path, video_src: str, audio_src: str | None) -> Path:
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error"]
    cmd += ["-f", "lavfi", "-i", video_src]
    if audio_src:
        cmd += ["-f", "lavfi", "-i", audio_src, "-shortest", "-c:a", "aac"]
    cmd += ["-pix_fmt", "yuv420p", "-y", str(out)]
    subprocess.run(cmd, check=True)
    return out


@pytest.fixture(scope="session")
def video_with_audio(sample_video) -> Path:
    """sample_video と同じ場所に置く、440Hz の音つきの 3 秒の動画 (許可ディレクトリ内)。"""
    return _make_media(
        sample_video.parent / "with_audio.mp4",
        "testsrc=duration=3:size=160x120:rate=10",
        "sine=frequency=440:duration=3",
    )


@pytest.fixture(scope="session")
def video_silent_audio(sample_video) -> Path:
    return _make_media(
        sample_video.parent / "silent_audio.mp4",
        "testsrc=duration=3:size=160x120:rate=10",
        "anullsrc=r=16000:cl=mono",
    )


class FakeWhisper:
    """mlx_whisper.transcribe の代わり。呼ばれた引数を覚える。"""

    def __init__(self, segments=None, error: Exception | None = None):
        self.calls: list[dict] = []
        self.segments = (
            segments
            if segments is not None
            else [{"start": 0.0, "end": 1.2, "text": " 左足に乗ってから回す"}]
        )
        self.error = error

    def __call__(self, audio, **kwargs):
        self.calls.append({"samples": len(audio), **kwargs})
        if self.error:
            raise self.error
        return {"segments": self.segments}


@pytest.fixture(autouse=True)
def no_real_whisper(monkeypatch):
    """テストで本物のモデル (約 1.6GB) を取りに行かないよう、既定の文字起こしを差し替える。"""
    from video_understanding import speech

    fake = FakeWhisper()
    monkeypatch.setattr(speech, "_default_transcribe", lambda: fake)
    return fake
