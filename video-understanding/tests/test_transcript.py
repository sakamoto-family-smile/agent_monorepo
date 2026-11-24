from video_understanding.transcript import (
    Segment,
    choose_caption,
    format_segments,
    format_timestamp,
    parse_json3,
    parse_vtt,
)


def _fmts(lang):
    return [{"ext": "vtt", "url": f"u/{lang}.vtt"}, {"ext": "json3", "url": f"u/{lang}.json3"}]


def test_manual_caption_in_requested_language_wins():
    info = {
        "subtitles": {"en": _fmts("en"), "ja": _fmts("ja")},
        "automatic_captions": {"ja-orig": _fmts("jo")},
    }
    t = choose_caption(info, "ja")
    assert (t.kind, t.lang, t.ext, t.url, t.translated_from) == (
        "captions_manual",
        "ja",
        "json3",
        "u/ja.json3",
        None,
    )


def test_manual_caption_in_other_language_beats_auto():
    info = {
        "subtitles": {"en": _fmts("en"), "live_chat": _fmts("lc")},
        "automatic_captions": {"ja-orig": _fmts("jo")},
    }
    assert choose_caption(info, "ja").lang == "en"


def test_auto_original_in_requested_language():
    info = {"automatic_captions": {"ja-orig": _fmts("jo"), "ja": _fmts("ja"), "en": _fmts("en")}}
    t = choose_caption(info, "ja")
    assert (t.kind, t.lang, t.url, t.translated_from) == ("captions_auto", "ja", "u/jo.json3", None)


def test_auto_translation_is_marked_when_youtube_detected_another_language():
    # 実例: 日本語の動画で YouTube が韓国語と判定し、ja は ko からの翻訳になっていた
    info = {"automatic_captions": {"ko-orig": _fmts("ko"), "ja": _fmts("ja")}}
    t = choose_caption(info, "ja")
    assert (t.lang, t.url, t.translated_from) == ("ja", "u/ja.json3", "ko")


def test_auto_other_original_when_no_requested_language():
    info = {"automatic_captions": {"en-orig": _fmts("en")}}
    t = choose_caption(info, "ja")
    assert (t.lang, t.translated_from) == ("en", None)


def test_vtt_used_when_no_json3_and_none_when_nothing():
    assert choose_caption({"subtitles": {"ja": [{"ext": "vtt", "url": "v"}]}}, "ja").ext == "vtt"
    assert choose_caption({"subtitles": {"ja": [{"ext": "srv1", "url": "x"}]}}, "ja") is None
    assert choose_caption({}, "ja") is None


def test_parse_json3_joins_segments_and_drops_newline_events():
    data = {
        "events": [
            {
                "tStartMs": 0,
                "dDurationMs": 1500,
                "segs": [{"utf8": "左足に"}, {"utf8": "乗ってから"}],
            },
            {"tStartMs": 1500, "dDurationMs": 10, "aAppend": 1, "segs": [{"utf8": "\n"}]},
            {"tStartMs": 1600, "dDurationMs": 1000, "segs": [{"utf8": "回す"}]},
            {"tStartMs": 2600, "dDurationMs": 900, "segs": [{"utf8": "回す"}]},
            {"dDurationMs": 5},
        ]
    }
    assert parse_json3(data) == [Segment(0.0, 1.5, "左足に乗ってから"), Segment(1.6, 3.5, "回す")]


def test_parse_vtt_rolling_auto_captions():
    vtt = """WEBVTT
Kind: captions

00:00:00.000 --> 00:00:02.000 align:start
<00:00:00.500><c>トップから</c>

00:00:02.000 --> 00:00:04.000
トップから
腰を一気に回すと

01:00:04.000 --> 01:00:05.500
腰を一気に回すと
"""
    assert parse_vtt(vtt) == [
        Segment(0.0, 2.0, "トップから"),
        Segment(2.0, 4.0, "腰を一気に回すと"),
    ]


def test_format_timestamp():
    assert format_timestamp(65.9) == "01:05"
    assert format_timestamp(3725) == "1:02:05"


def test_format_segments_truncates():
    segs = [Segment(i, i + 1, "あいうえお") for i in range(5)]
    text, cut = format_segments(segs, max_chars=40)
    assert cut and text.splitlines() == ["[00:00] あいうえお", "[00:01] あいうえお"]
    assert format_segments(segs[:1], 100) == ("[00:00] あいうえお", False)
