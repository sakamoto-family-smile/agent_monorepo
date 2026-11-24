from pathlib import Path

import pytest

from video_understanding.cache import Cache
from video_understanding.config import ConfigError, load_config


def test_defaults():
    cfg = load_config({})
    assert cfg.cache_dir == Path("~/.cache/video-understanding").expanduser()
    assert cfg.allowed_dirs == ()
    assert (cfg.video_ttl_days, cfg.max_duration_sec) == (14, 1800)


def test_overrides(tmp_path):
    cfg = load_config(
        {
            "VIDEO_UNDERSTANDING_CACHE_DIR": str(tmp_path),
            "VIDEO_UNDERSTANDING_ALLOWED_DIRS": f"{tmp_path}/a::{tmp_path}/b",
            "VIDEO_UNDERSTANDING_MAX_DURATION_SEC": "60",
        }
    )
    assert cfg.cache_dir == tmp_path
    assert cfg.allowed_dirs == (tmp_path / "a", tmp_path / "b")
    assert cfg.max_duration_sec == 60


@pytest.mark.parametrize("raw", ["abc", "0", "-5"])
def test_invalid_int(raw):
    with pytest.raises(ConfigError):
        load_config({"VIDEO_UNDERSTANDING_VIDEO_TTL_DAYS": raw})


def test_cache_dir_for_creates_and_marks_use(tmp_path):
    d = Cache(tmp_path).dir_for("yt-Fgv4M8NgSZ0")
    assert d == tmp_path / "yt-Fgv4M8NgSZ0" and d.is_dir()
    assert (d / ".last_used").read_text().isdigit()


@pytest.mark.parametrize("key", ["../x", "yt-short", "local-XYZ", "foo"])
def test_cache_rejects_bad_keys(tmp_path, key):
    with pytest.raises(ValueError):
        Cache(tmp_path).dir_for(key)
