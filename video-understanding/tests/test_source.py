import os

import pytest

from video_understanding.source import SourceError, parse_source

VID = "Fgv4M8NgSZ0"


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={VID}",
        f"https://youtube.com/watch?v={VID}&list=PL123&t=30s",
        f"https://m.youtube.com/watch?v={VID}",
        f"https://youtube.com/shorts/{VID}?si=abc",
        f"https://www.youtube.com/live/{VID}",
        f"https://youtu.be/{VID}?t=5",
        f"  https://youtu.be/{VID}  ",
    ],
)
def test_accepts_single_video_urls(url):
    src = parse_source(url, [])
    assert src.kind == "youtube"
    assert src.key == f"yt-{VID}"
    assert src.url == f"https://www.youtube.com/watch?v={VID}"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/watch?list=PL123",
        "https://www.youtube.com/@channel",
        "https://youtu.be/",
        f"https://www.youtube.com/watch?v={VID}x",
    ],
)
def test_rejects_non_single_video_youtube_urls(url):
    with pytest.raises(SourceError, match="1 本"):
        parse_source(url, [])


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/watch?v=Fgv4M8NgSZ0",
        "https://youtube.com.evil.example/watch?v=Fgv4M8NgSZ0",
        "file:///etc/passwd",
        "ftp://youtube.com/watch?v=Fgv4M8NgSZ0",
    ],
)
def test_rejects_other_urls(url):
    with pytest.raises(SourceError, match="YouTube 以外"):
        parse_source(url, [])


def test_rejects_empty():
    with pytest.raises(SourceError):
        parse_source("  ", [])


def test_local_file_inside_allowed_dir(sample_video):
    src = parse_source(str(sample_video), [sample_video.parent])
    assert src.kind == "local"
    assert src.path == sample_video.resolve()
    assert src.key.startswith("local-") and len(src.key) == len("local-") + 16


def test_local_key_depends_on_content_not_path(sample_video, tmp_path):
    copy = tmp_path / "renamed.mp4"
    copy.write_bytes(sample_video.read_bytes())
    a = parse_source(str(sample_video), [sample_video.parent])
    b = parse_source(str(copy), [tmp_path])
    assert a.key == b.key


def test_local_requires_allowed_dirs(sample_video):
    with pytest.raises(SourceError, match="未設定"):
        parse_source(str(sample_video), [])


def test_local_outside_allowed_dir(sample_video, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    with pytest.raises(SourceError, match="外のファイル"):
        parse_source(str(sample_video), [allowed])


def test_local_dotdot_escape(sample_video, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    sneaky = allowed / ".." / ".." / sample_video.parent.name / sample_video.name
    with pytest.raises(SourceError):
        parse_source(str(sneaky), [allowed])


def test_local_symlink_pointing_outside(sample_video, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    link = allowed / "link.mp4"
    os.symlink(sample_video, link)
    with pytest.raises(SourceError, match="外のファイル"):
        parse_source(str(link), [allowed])


def test_local_missing_and_directory(tmp_path):
    with pytest.raises(SourceError, match="見つかりません"):
        parse_source(str(tmp_path / "nope.mp4"), [tmp_path])
    with pytest.raises(SourceError, match="ファイルではありません"):
        parse_source(str(tmp_path), [tmp_path])
