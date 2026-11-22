"""fetch_media: 変換待ち・保存先・重複・失敗の再試行と通知。"""
from __future__ import annotations

import hashlib

from app.jobs import queue
from app.line.api import LineApiError
from tests.conftest import ME, Env

VIDEO = b"\x00\x00\x00\x18ftypmp42fake-video"
IMAGE = b"\xff\xd8\xfffake-jpeg"


async def test_video_waits_for_transcoding_then_saves(env: Env):
    env.line.transcoding["m1"] = ["processing", "processing", "succeeded"]
    env.line.contents["m1"] = (VIDEO, "video/mp4")
    await env.post(env.media_event("video", "m1"))
    assert "🎥 動画を受け付けました" in env.line.reply_texts()[0]

    for _ in range(2):
        assert await env.run_jobs() == 1
        assert await env.scalar("SELECT status FROM media") == "pending"
        assert await env.run_jobs() == 0  # 10 秒後まで待つ
        env.clock.advance(seconds=10)
    await env.run_jobs()

    row = (await env.rows("SELECT * FROM media"))[0]
    digest = hashlib.sha256(VIDEO).hexdigest()
    assert row["status"] == "saved" and row["sha256"] == digest
    assert row["path"] == f"media/2026/11/{digest}.mp4"
    assert row["duration_ms"] == 4200 and row["kind"] == "video"
    assert (env.deps.settings.paths.root / row["path"]).read_bytes() == VIDEO
    job = (await env.rows("SELECT * FROM jobs"))[0]
    assert job["status"] == "done" and job["attempts"] == 0 and job["polls"] == 2
    assert not list(env.deps.settings.paths.tmp.iterdir())


async def test_image_is_saved_without_transcoding(env: Env):
    env.line.contents["i1"] = (IMAGE, "image/jpeg")
    await env.post(env.media_event("image", "i1"))
    await env.run_jobs()
    row = (await env.rows("SELECT * FROM media"))[0]
    assert row["status"] == "saved" and row["path"].endswith(".jpg")


async def test_same_content_twice_shares_one_file(env: Env):
    env.line.contents["i1"] = (IMAGE, "image/jpeg")
    env.line.contents["i2"] = (IMAGE, "image/jpeg")
    await env.post(env.media_event("image", "i1"), env.media_event("image", "i2"))
    await env.run_jobs()
    paths = [r["path"] for r in await env.rows("SELECT path FROM media")]
    assert len(paths) == 2 and paths[0] == paths[1]
    assert len(list((env.deps.settings.paths.media).rglob("*.jpg"))) == 1


async def test_transient_failure_retries_with_backoff(env: Env):
    env.line.download_errors["i1"] = LineApiError(500, "oops")
    await env.post(env.media_event("image", "i1"))
    await env.run_jobs()
    job = (await env.rows("SELECT * FROM jobs"))[0]
    assert job["status"] == "pending" and job["attempts"] == 1 and "500" in job["last_error"]

    del env.line.download_errors["i1"]
    env.line.contents["i1"] = (IMAGE, "image/jpeg")
    assert await env.run_jobs() == 0
    env.clock.advance(seconds=30)
    await env.run_jobs()
    assert await env.scalar("SELECT status FROM media") == "saved"


async def test_gives_up_after_max_attempts_and_pushes(env: Env):
    env.line.download_errors["i1"] = LineApiError(503, "unavailable")
    await env.post(env.media_event("image", "i1"))
    for _ in range(queue.MAX_ATTEMPTS):
        await env.run_jobs()
        env.clock.advance(hours=1)

    assert await env.scalar("SELECT status FROM jobs") == "failed"
    assert await env.scalar("SELECT status FROM media") == "failed"
    assert len(env.line.pushes) == 1
    to, messages, _ = env.line.pushes[0]
    assert to == ME and "画像を LINE から取得できませんでした" in messages[0]["text"]
    assert await env.scalar("SELECT kind FROM push_log") == "failure"


async def test_expired_content_fails_immediately(env: Env):
    env.line.download_errors["i1"] = LineApiError(404, "not found")
    await env.post(env.media_event("image", "i1"))
    await env.run_jobs()
    assert await env.scalar("SELECT status FROM jobs") == "failed"
    assert len(env.line.pushes) == 1


async def test_transcoding_failed_is_permanent(env: Env):
    env.line.transcoding["m1"] = ["failed"]
    await env.post(env.media_event("video", "m1"))
    await env.run_jobs()
    assert await env.scalar("SELECT status FROM media") == "failed"


async def test_external_content_is_not_fetched(env: Env):
    ev = env.media_event("video", "m1")
    ev["message"]["contentProvider"] = {"type": "external", "originalContentUrl": "https://example.com/x.mp4"}
    await env.post(ev)
    await env.run_jobs()
    job = (await env.rows("SELECT * FROM jobs"))[0]
    assert job["status"] == "failed" and "external" in job["last_error"]


async def test_running_jobs_are_reset_on_restart(env: Env):
    env.line.contents["i1"] = (IMAGE, "image/jpeg")
    await env.post(env.media_event("image", "i1"))
    async with env.deps.engine.begin() as conn:
        claimed = await queue.claim_due(conn, env.clock())
        assert len(claimed) == 1
        assert await queue.reset_running(conn, env.clock()) == 1
    await env.run_jobs()
    assert await env.scalar("SELECT status FROM media") == "saved"


async def test_undo_media(env: Env):
    env.line.contents["i1"] = (IMAGE, "image/jpeg")
    await env.post(env.media_event("image", "i1"))
    assert (await env.send_text("取消")).startswith("↩️ 直前の動画・画像を取り消しました")
    assert await env.scalar("SELECT deleted_at IS NOT NULL FROM media") == 1
