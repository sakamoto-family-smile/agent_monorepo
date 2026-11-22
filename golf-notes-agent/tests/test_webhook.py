"""webhook: 署名・許可リスト・原本の保存・重複・メモ・取消。"""
from __future__ import annotations

import json

from app.line.events import signature
from tests.conftest import ME, SECRET, STRANGER, Env


async def test_rejects_bad_or_missing_signature(env: Env):
    assert (await env.post(env.text_event("x"), sign="bogus")).status_code == 401
    assert (await env.post(env.text_event("x"), sign="")).status_code == 401
    assert await env.scalar("SELECT count(*) FROM raw_events") == 0


async def test_verify_button_with_no_events(env: Env):
    # LINE Developers の「検証」は events が空で届く
    body = json.dumps({"destination": "U", "events": []}).encode()
    res = await env.client.post(
        "/api/line/webhook", content=body, headers={"X-Line-Signature": signature(body, SECRET)}
    )
    assert res.status_code == 200


async def test_drops_non_allowed_user_silently(env: Env):
    res = await env.post(env.text_event("hello", user=STRANGER))
    assert res.status_code == 200
    assert env.line.replies == []
    assert await env.scalar("SELECT count(*) FROM raw_events") == 0
    assert not list(env.deps.settings.paths.raw.rglob("*.json"))


async def test_drops_group_events(env: Env):
    ev = env.text_event("hello")
    ev["source"] = {"type": "group", "groupId": "G1", "userId": ME}
    await env.post(ev)
    assert await env.scalar("SELECT count(*) FROM raw_events") == 0


async def test_memo_saved_with_raw_original(env: Env):
    reply = await env.send_text("右に出る。トップで左手首が甲側に折れてる")

    assert reply == "📝 メモを保存しました ｜ 11/22 の練習（仮）"
    memo = (await env.rows("SELECT * FROM memos"))[0]
    assert memo["text"] == "右に出る。トップで左手首が甲側に折れてる"
    raw = (await env.rows("SELECT * FROM raw_events"))[0]
    assert raw["user_id"] == ME and raw["type"] == "message" and raw["message_type"] == "text"
    files = list(env.deps.settings.paths.raw.rglob("*.json"))
    assert len(files) == 1 and files[0].parent.parts[-2:] == ("2026", "11")
    assert json.loads(files[0].read_text())["message"]["text"].startswith("右に出る")


async def test_same_webhook_event_is_saved_once(env: Env):
    ev = env.text_event("同じイベント")
    await env.post(ev)
    redelivered = {**ev, "deliveryContext": {"isRedelivery": True}}
    await env.post(redelivered)
    await env.post(ev, ev)

    assert await env.scalar("SELECT count(*) FROM raw_events") == 1
    assert await env.scalar("SELECT count(*) FROM memos") == 1
    assert len(env.line.replies) == 1


async def test_postbacks_without_message_id_are_deduplicated(env: Env):
    ev = env.postback_event("action=noop")
    await env.post(ev)
    await env.post(ev)
    rows = await env.rows("SELECT * FROM raw_events")
    assert len(rows) == 1 and rows[0]["line_message_id"] is None


async def test_redelivered_event_is_saved_but_not_replied(env: Env):
    await env.post(env.text_event("再送で初めて届いた", redelivery=True))
    assert await env.scalar("SELECT count(*) FROM memos") == 1
    assert env.line.replies == []


async def test_failed_handling_keeps_raw_and_retries(env: Env, monkeypatch):
    from app.handlers import dispatch

    original = dispatch.handle

    async def flaky(ctx):
        if ctx.ev.text == "boom":
            raise RuntimeError("boom")
        return await original(ctx)

    monkeypatch.setattr(dispatch, "handle", flaky)
    res = await env.post(env.text_event("boom"), env.text_event("ok"))
    assert res.status_code == 200
    # 失敗したイベントも原本は DB に残り、やり直しのジョブが積まれる。成功したほうはジョブが消える
    assert await env.scalar("SELECT count(*) FROM raw_events") == 2
    assert [r["text"] for r in await env.rows("SELECT text FROM memos")] == ["ok"]
    jobs = await env.rows("SELECT kind, ref_id, status FROM jobs")
    assert jobs == [{"kind": "redispatch", "ref_id": 1, "status": "pending"}]
    assert env.line.reply_texts()[0].startswith("⚠️ 保存の途中でエラーが起きました")

    monkeypatch.setattr(dispatch, "handle", original)
    assert await env.run_jobs() == 0  # 2 分の猶予のあと
    env.clock.advance(minutes=2)
    await env.run_jobs()
    assert sorted(r["text"] for r in await env.rows("SELECT text FROM memos")) == ["boom", "ok"]
    assert await env.scalar("SELECT status FROM jobs") == "done"
    assert env.line.pushes[0][1][0]["text"].startswith("（やり直して保存しました）\n📝 メモを保存しました")


async def test_successful_handling_leaves_no_retry_job(env: Env):
    await env.send_text("ふつうのメモ")
    assert await env.scalar("SELECT count(*) FROM jobs") == 0


async def test_too_large_body_is_rejected_before_signature(env: Env):
    body = b"x" * (1024 * 1024 + 1)
    res = await env.client.post("/api/line/webhook", content=body, headers={"X-Line-Signature": "x"})
    assert res.status_code == 413


async def test_non_ascii_signature_is_401(env: Env):
    body = b'{"events": []}'
    res = await env.client.post(
        "/api/line/webhook", content=body, headers={"X-Line-Signature": "署名".encode()}
    )
    assert res.status_code == 401


async def test_malformed_postback_is_ignored(env: Env):
    data = "&".join(f"k{i}=v" for i in range(20))
    res = await env.post(env.postback_event(data))
    assert res.status_code == 200 and env.line.replies == []
    assert await env.scalar("SELECT count(*) FROM jobs") == 0


async def test_undo_uses_arrival_order_within_the_same_second(env: Env):
    env.line.contents["i1"] = (b"img", "image/jpeg")
    await env.post(env.media_event("image", "i1"), env.text_event("同じ秒のメモ"))
    assert (await env.send_text("取消")).startswith("↩️ 直前のメモ")


async def test_unsupported_message_type(env: Env):
    await env.post(env.event(message={"type": "sticker", "id": "s1", "packageId": "1", "stickerId": "2"}))
    assert "対象外" in env.line.reply_texts()[0]
    assert await env.scalar("SELECT count(*) FROM raw_events") == 1


async def test_undo_latest_entry(env: Env):
    await env.send_text("1 つ目")
    env.clock.advance(seconds=5)
    await env.send_text("2 つ目")
    env.clock.advance(seconds=5)

    reply = await env.send_text("取消")

    assert reply.startswith("↩️ 直前のメモを取り消しました")
    rows = await env.rows("SELECT text, deleted_at FROM memos ORDER BY id")
    assert rows[0]["deleted_at"] is None and rows[1]["deleted_at"] is not None
    assert await env.send_text("取消") == "↩️ 直前のメモを取り消しました（#1）。"
    assert await env.send_text("取消") == "取り消せるものがありません。"


async def test_not_configured_returns_503(tmp_path):
    import httpx

    from app.main import close_deps, create_app, open_deps
    from tests.conftest import FakeClock, FakeLine, make_settings

    settings = make_settings(tmp_path, line_channel_secret="")
    deps = await open_deps(settings, FakeLine(), FakeClock())
    app = create_app(settings)
    app.state.deps = deps
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        res = await c.post("/api/line/webhook", content=b"{}", headers={"X-Line-Signature": "x"})
    await close_deps(deps)
    assert res.status_code == 503


async def test_healthz(env: Env):
    assert (await env.client.get("/healthz")).json() == {"ok": True}
