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


def test_whisper_settings():
    from video_understanding.config import DEFAULT_WHISPER_MODEL

    d = load_config({})
    assert d.whisper_model == DEFAULT_WHISPER_MODEL and "切り返し" in d.whisper_prompt
    c = load_config(
        {
            "VIDEO_UNDERSTANDING_WHISPER_MODEL": "mlx-community/whisper-small",
            "VIDEO_UNDERSTANDING_WHISPER_PROMPT": "",
        }
    )
    assert c.whisper_model == "mlx-community/whisper-small" and c.whisper_prompt == ""


def _entry(root, key, age_days, now, files=("video.mp4", "info.json")):
    d = root / key
    (d / "frames").mkdir(parents=True)
    (d / "frames" / "000.000.jpg").write_bytes(b"x" * 10)
    for name in files:
        (d / name).write_bytes(b"y" * 100)
    (d / ".last_used").write_text(str(int(now - age_days * 86400)))
    return d


def test_gc_removes_only_expired_media(tmp_path):
    from video_understanding.cache import gc

    now = 1_800_000_000
    old = _entry(
        tmp_path,
        "yt-AAAAAAAAAAA",
        15,
        now,
        ("video.mp4", "video.f1.mp4.part", "info.json", "whisper-ja-x.json"),
    )
    fresh = _entry(tmp_path, "yt-BBBBBBBBBBB", 13, now)
    stranger = _entry(tmp_path, "not-a-cache-key", 99, now)

    dry = gc(tmp_path, 14, now=now, dry_run=True)
    assert dry.expired == [old] and dry.freed_bytes == 210
    assert (old / "video.mp4").exists()

    r = gc(tmp_path, 14, now=now)
    assert r.expired == [old] and r.freed_bytes == 210
    assert sorted(p.name for p in old.iterdir()) == [".last_used", "info.json", "whisper-ja-x.json"]
    assert (fresh / "video.mp4").exists() and (fresh / "frames").exists()
    assert (stranger / "video.mp4").exists()
    # 2 回目は消すものが無い
    assert gc(tmp_path, 14, now=now).expired == []


def test_gc_missing_root_and_marker(tmp_path):
    import os

    from video_understanding.cache import gc

    assert gc(tmp_path / "nope", 14).expired == []
    d = tmp_path / "local-0123456789abcdef"
    (d / "sheets").mkdir(parents=True)
    os.utime(d, (0, 0))  # .last_used が無ければディレクトリの更新時刻で判断する
    assert gc(tmp_path, 14).expired == [d]
