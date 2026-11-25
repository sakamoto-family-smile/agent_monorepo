import asyncio
import json

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from mcp.types import ImageContent, TextContent

from video_understanding import fetch
from video_understanding.server import mcp

from fakes import make_factory

URL = "https://youtu.be/Fgv4M8NgSZ0"
CAPTION = json.dumps(
    {"events": [{"tStartMs": 1000, "dDurationMs": 900, "segs": [{"utf8": "左足に乗ってから回す"}]}]}
)


@pytest.fixture
def env(cfg, sample_video, monkeypatch):
    monkeypatch.setenv("VIDEO_UNDERSTANDING_CACHE_DIR", str(cfg.cache_dir))
    monkeypatch.setenv("VIDEO_UNDERSTANDING_ALLOWED_DIRS", str(sample_video.parent))
    info = {
        "id": "Fgv4M8NgSZ0",
        "title": "レッスン",
        "duration": 3,
        "webpage_url": "https://www.youtube.com/watch?v=Fgv4M8NgSZ0",
        "subtitles": {"ja": [{"ext": "json3", "url": "cap"}]},
    }
    factory = make_factory(info=info, video=sample_video, captions={"cap": CAPTION})
    monkeypatch.setattr(fetch, "_default_factory", factory)
    return factory


def call(name, args):
    async def go():
        async with Client(mcp) as client:
            return await client.call_tool(name, args)

    return asyncio.run(go())


def test_lists_three_read_only_tools():
    async def go():
        async with Client(mcp) as client:
            return await client.list_tools()

    tools = {t.name: t for t in asyncio.run(go())}
    assert set(tools) == {"video_overview", "video_frames", "video_transcript"}
    assert all(t.annotations.read_only_hint for t in tools.values())


def test_overview_returns_text_and_images(env):
    res = call("video_overview", {"source": URL})
    text, *images = res.content
    assert isinstance(text, TextContent) and "左足に乗ってから回す" in text.text
    assert '<untrusted_video_text source="captions">' in text.text
    assert len(images) == 1 and isinstance(images[0], ImageContent)
    assert images[0].mime_type == "image/jpeg"


def test_frames_local_file(env, sample_video):
    res = call(
        "video_frames",
        {"source": str(sample_video), "start": 0, "end": 2.9, "fps": 10, "crop": "0,0,0.5,1"},
    )
    text, *images = res.content
    assert "コマ: 30 枚" in text.text and len(images) == 2


def test_transcript(env):
    res = call("video_transcript", {"source": URL})
    assert "[00:01] 左足に乗ってから回す" in res.content[0].text
    assert "手動字幕 (ja)" in res.content[0].text


def test_user_errors_become_tool_errors(env):
    with pytest.raises(ToolError, match="YouTube 以外"):
        call("video_overview", {"source": "https://example.com/v"})
    with pytest.raises(ToolError, match="上限"):
        call("video_frames", {"source": URL, "start": 0, "end": 3, "fps": 30})


def test_argument_validation(env):
    with pytest.raises(ToolError):
        call("video_frames", {"source": URL, "start": 0, "end": 1, "fps": 60})


def test_transcript_force_whisper(env, video_with_audio, no_real_whisper):
    res = call("video_transcript", {"source": str(video_with_audio), "force_whisper": True})
    assert "文字起こし (mlx-whisper" in res.content[0].text
    assert len(no_real_whisper.calls) == 1
