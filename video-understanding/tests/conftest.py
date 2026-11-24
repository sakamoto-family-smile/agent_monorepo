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
