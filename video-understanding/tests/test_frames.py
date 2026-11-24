import pytest
from PIL import Image

from video_understanding import frames as fr


@pytest.mark.parametrize(
    ("duration", "expected"),
    [(4.5, 0.25), (15, 0.5), (36, 1), (60, 2), (600, 15), (1800, 60), (100000, 2500)],
)
def test_auto_interval_keeps_overview_within_cap(duration, expected):
    assert fr.auto_interval(duration) == expected


def test_sample_times():
    assert fr.sample_times(3.0, 1.0) == [0, 1, 2]
    assert fr.sample_times(0.4, 1.0) == [0]
    with pytest.raises(fr.FramesError, match="上限"):
        fr.sample_times(100, 1.0)
    with pytest.raises(fr.FramesError):
        fr.sample_times(10, 0)


def test_range_times_inclusive_and_clamped():
    assert fr.range_times(2.0, 2.3, 10, duration=5) == [2.0, 2.1, 2.2, 2.3]
    assert fr.range_times(1.0, 9.0, 2, duration=2.6) == [1.0, 1.5, 2.0, 2.5]


@pytest.mark.parametrize(
    ("start", "end", "fps", "msg"),
    [
        (0, 1, 31, "fps"),
        (0, 1, 0, "fps"),
        (2, 1, 10, "区間"),
        (-1, 1, 10, "区間"),
        (6, 7, 10, "長さ"),
        (0, 2, 30, "上限"),
    ],
)
def test_range_times_rejects(start, end, fps, msg):
    with pytest.raises(fr.FramesError, match=msg):
        fr.range_times(start, end, fps, duration=5)


def test_crop_parse():
    c = fr.Crop.parse("0.2,0,0.6,1")
    assert c == fr.Crop(0.2, 0, 0.6, 1)
    assert c.ffmpeg_filter() == "crop=iw*0.6:ih*1.0:iw*0.2:ih*0.0"
    for bad in ["0.5,0,0.6,1", "a,b,c,d", "0,0,0,1", "0,0,1"]:
        with pytest.raises(fr.FramesError):
            fr.Crop.parse(bad)


def test_probe(sample_video):
    meta = fr.probe(sample_video)
    assert meta.duration == pytest.approx(3.0, abs=0.1)
    assert (meta.width, meta.height, meta.fps) == (160, 120, 10)


def test_extract_and_reuse(sample_video, tmp_path):
    frames = fr.extract(sample_video, [0, 1.5], tmp_path)
    assert [f.t for f in frames] == [0, 1.5]
    assert all(f.path.exists() for f in frames)
    mtime = frames[0].path.stat().st_mtime_ns
    assert fr.extract(sample_video, [0], tmp_path)[0].path.stat().st_mtime_ns == mtime


def test_extract_with_crop(sample_video, tmp_path):
    [frame] = fr.extract(sample_video, [1.0], tmp_path, fr.Crop(0.5, 0, 0.5, 0.5))
    assert Image.open(frame.path).size == (80, 60)
    assert "_c0.5_0_0.5_0.5" in frame.path.name


def test_contact_sheet_size_and_grid(sample_video, tmp_path):
    frames = fr.extract(sample_video, [i * 0.1 for i in range(20)], tmp_path / "f")
    sheet = fr.contact_sheet(frames, tmp_path / "s.jpg", max_px=400)
    w, h = Image.open(sheet).size
    assert max(w, h) <= 400
    assert w / h == pytest.approx(1, abs=0.5)  # なるべく正方形


def test_contact_sheet_limits(tmp_path):
    with pytest.raises(fr.FramesError):
        fr.contact_sheet([], tmp_path / "x.jpg")
    with pytest.raises(fr.FramesError, match="20"):
        fr.contact_sheet([fr.Frame(0, tmp_path)] * 21, tmp_path / "x.jpg")


def test_chunk():
    items = [fr.Frame(i, None) for i in range(45)]
    assert [len(c) for c in fr.chunk(items)] == [20, 20, 5]
