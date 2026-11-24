import json

import pytest

from video_understanding.fetch import FORMAT, FetchError, fetch_youtube

from fakes import make_factory

URL = "https://www.youtube.com/watch?v=Fgv4M8NgSZ0"
JSON3 = json.dumps(
    {"events": [{"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "こんにちは"}]}]}
)


def _info(**extra):
    return {
        "id": "Fgv4M8NgSZ0",
        "title": "t",
        "duration": 3,
        "formats": [],
        "automatic_captions": {"ja-orig": [{"ext": "json3", "url": "cap"}]},
        **extra,
    }


def test_downloads_video_and_caption_then_serves_from_cache(tmp_path, sample_video):
    f = make_factory(info=_info(), video=sample_video, captions={"cap": JSON3})
    got = fetch_youtube(URL, tmp_path, "ja", 1800, f)
    assert got.video.exists() and got.caption_body == JSON3
    assert got.caption.kind == "captions_auto"
    assert json.loads((tmp_path / "info.json").read_text())["title"] == "t"
    assert [c[0] for c in f.calls] == ["extract_info", "urlopen", "download"]
    assert f.calls[2][2] == FORMAT

    again = fetch_youtube(URL, tmp_path, "ja", 1800, f)
    assert len(f.calls) == 3  # ネットワークに出ていない
    assert again.caption_body == JSON3 and again.caption.lang == "ja" and again.caption.url == ""


def test_format_keeps_short_side_480_for_vertical_video():
    assert "[height<=854][width<=854]" in FORMAT


def test_caption_failure_keeps_video_and_is_retried(tmp_path, sample_video):
    f = make_factory(info=_info(), video=sample_video, captions={"cap": OSError("HTTP Error 429")})
    got = fetch_youtube(URL, tmp_path, "ja", 1800, f)
    assert got.video.exists() and got.caption_body is None and "429" in got.caption_error
    assert not (tmp_path / "caption-ja.json").exists()
    fetch_youtube(URL, tmp_path, "ja", 1800, f)
    assert [c[0] for c in f.calls].count("extract_info") == 2
    assert [c[0] for c in f.calls].count("download") == 1  # 動画は取り直さない


def test_no_caption_is_cached(tmp_path, sample_video):
    f = make_factory(info=_info(automatic_captions={}), video=sample_video)
    assert fetch_youtube(URL, tmp_path, "ja", 1800, f).caption is None
    assert fetch_youtube(URL, tmp_path, "ja", 1800, f).caption is None
    assert len(f.calls) == 2


@pytest.mark.parametrize(
    ("extra", "msg"),
    [
        ({"duration": 4000}, "長すぎ"),
        ({"is_live": True}, "配信"),
        ({"live_status": "is_upcoming"}, "配信"),
    ],
)
def test_refuses_long_or_live(tmp_path, sample_video, extra, msg):
    f = make_factory(info=_info(**extra), video=sample_video)
    with pytest.raises(FetchError, match=msg):
        fetch_youtube(URL, tmp_path, "ja", 1800, f)
    assert not (tmp_path / "video.mp4").exists()


def test_ytdlp_errors_become_fetch_error(tmp_path, sample_video):
    from yt_dlp.utils import DownloadError

    def factory(opts):
        raise DownloadError("Video unavailable")

    with pytest.raises(FetchError, match="Video unavailable"):
        fetch_youtube(URL, tmp_path, "ja", 1800, factory)
