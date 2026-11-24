"""実際に YouTube へ取りに行く。CI では動かさない (`uv run pytest -m network` で手動実行)。"""

import pytest

from video_understanding import api

pytestmark = pytest.mark.network

SHORT = "https://youtube.com/shorts/Fgv4M8NgSZ0"


def test_overview_and_frames_on_public_short(cfg):
    r = api.overview(SHORT, cfg)
    assert r.prepared.meta.duration > 0 and r.sheets
    assert min(r.prepared.meta.width, r.prepared.meta.height) <= 480
    # 字幕は YouTube が 429 で断ることがあるので、取れたか理由が書かれているかのどちらか
    assert r.prepared.transcript is not None or r.prepared.transcript_note
    f = api.frames(SHORT, cfg, 1.0, 2.0, fps=5)
    assert len(f.times) == 6
