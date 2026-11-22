"""計測テキストの取り込み (webhook から): 計測モード・自動判定・セッションの決め方・確認・付け替え。"""
from __future__ import annotations

import json

from tests.conftest import Env
from tests.test_lesson_parser import SAMPLE
from tests.test_modes import press, quick_data

# 2026-11-22 10:00 JST に、当日 09:55 の計測を貼る想定
TODAY = SAMPLE.replace("2026/10/07 17:09", "2026/11/22 09:55")


def last_reply(env: Env) -> dict:
    return env.line.replies[-1][1][0]


async def test_metrics_mode_saves_shot_and_extends(env: Env):
    msg = await press(env, "action=mode&mode=metrics")
    assert msg["text"].startswith("📊 計測テキストを貼ってください") and "計測モード" in msg["text"]

    reply = await env.send_text(TODAY)

    assert reply.startswith("⛳ 7I 1 球を保存（キャリー 131.4yd / 左 6.5yd） ｜ 計測モード・11/22 のレッスン（仮）")
    assert quick_data(last_reply(env)) == ["action=reassign&capture=1"]  # 検算 OK なので確定済み
    capture = (await env.rows("SELECT * FROM lesson_captures"))[0]
    assert capture["status"] == "confirmed" and capture["source"] == "text" and capture["parser_version"] == "1"
    metric = (await env.rows("SELECT * FROM v_launch_metrics"))[0]
    assert metric["club"] == "7I" and metric["offline_yd"] == -6.5 and metric["sidespin_rpm"] == -857
    assert round(metric["face_to_path_deg"], 1) == -3.9
    assert metric["shot_at"] == "2026-11-22T00:55:00Z"
    assert json.loads(metric["labels_json"])["club"] == "7アイアン"
    assert json.loads(metric["check_flags"]) == []

    # 何回かに分けて貼れる。モードは延びる
    env.clock.advance(minutes=25)
    second = TODAY.replace("09:55", "10:20").replace("7アイアン", "PW")
    assert (await env.send_text(second)).startswith("⛳ PW 1 球を保存")
    env.clock.advance(minutes=25)
    assert (await env.send_text(TODAY)).endswith("計測モード・11/22 のレッスン（仮）")


async def test_multiple_shots_in_one_message(env: Env):
    await press(env, "action=mode&mode=metrics")
    text = "\n".join([TODAY, TODAY.replace("09:55", "09:56"), TODAY.replace("09:55 7アイアン", "09:57 PW")])
    assert (await env.send_text(text)).startswith("⛳ 3 球を保存（7I×2・PW×1）")
    assert await env.scalar("SELECT count(*) FROM launch_metrics") == 3


async def test_auto_detect_without_button(env: Env):
    reply = await env.send_text(TODAY)
    assert reply.startswith("⛳ 7I 1 球を保存")
    assert "計測として保存しました（違えば「取消」）" in reply
    assert await env.scalar("SELECT count(*) FROM memos") == 0
    assert (await env.send_text("取消")).startswith("↩️ 直前の計測を取り消しました")
    assert await env.scalar("SELECT count(*) FROM v_launch_metrics") == 0


async def test_flagged_shot_waits_for_confirmation(env: Env):
    await press(env, "action=mode&mode=metrics")
    reply = await env.send_text(TODAY.replace("飛距離: 149.9yd", "飛距離: 155.0yd"))
    assert "⚠️ 1 球目 7I: 飛距離がキャリー + ランと合いません（差 +5.1yd）" in reply
    assert quick_data(last_reply(env)) == [
        "action=capture&id=1&status=confirmed",
        "action=capture&id=1&status=rejected",
        "action=reassign&capture=1",
    ]
    assert await env.scalar("SELECT status FROM lesson_captures") == "pending"
    assert await env.scalar("SELECT count(*) FROM v_launch_metrics") == 0

    assert (await press(env, "action=capture&id=1&status=confirmed"))["text"] == "📊 計測 #1 を確定しました。"
    assert await env.scalar("SELECT count(*) FROM v_launch_metrics") == 1
    assert await press(env, "action=capture&id=1&status=deleted") == {}


async def test_unreadable_lines_are_listed(env: Env):
    await press(env, "action=mode&mode=metrics")
    reply = await env.send_text(TODAY + "\nなにか別の行")
    assert "読めなかった行: 7 行目" in reply


async def test_nothing_readable_offers_memo(env: Env):
    await press(env, "action=mode&mode=metrics")
    reply = await env.send_text("今日のレッスンはフェースの向き")
    assert reply.startswith("📊 計測として読み取れませんでした")
    data = quick_data(last_reply(env))
    assert data == ["action=memo_from&raw=2"]
    assert await env.scalar("SELECT count(*) FROM memos") == 0

    assert (await press(env, data[0]))["text"].startswith("📝 メモとして保存しました")
    assert await env.scalar("SELECT text FROM memos") == "今日のレッスンはフェースの向き"
    assert await press(env, data[0]) == {}  # 2 回押しても 1 件
    assert await env.scalar("SELECT count(*) FROM memos") == 1


async def test_past_metrics_go_to_their_own_date(env: Env):
    # 11/22 の練習中に、10/07 のレッスンの計測を貼る
    await press(env, "action=session_start&kind=practice")
    reply = await env.send_text(SAMPLE)
    assert reply.splitlines()[0] == "⛳ 7I 1 球を保存（キャリー 131.4yd / 左 6.5yd） ｜ 10/7 のレッスン（仮）"
    session = (await env.rows("SELECT s.* FROM sessions s JOIN lesson_captures c ON c.session_id = s.id"))[0]
    assert session["date"] == "2026-10-07" and session["kind"] == "lesson" and session["provisional"] == 1
    # 練習のセッションは開いたまま
    assert (await env.send_text("練習のメモ")).endswith("11/22 の練習")


async def test_metrics_during_open_lesson_go_to_it(env: Env):
    await press(env, "action=session_start&kind=lesson")
    env.clock.advance(minutes=20)
    reply = await env.send_text(TODAY.replace("09:55", "10:10"))
    assert reply.splitlines()[0].endswith("11/22 のレッスン")
    assert await env.scalar("SELECT session_id FROM lesson_captures") == 1


async def test_metrics_before_the_session_started_use_the_day_lesson(env: Env):
    # 練習を 10:00 に開始。09:55 の計測は開始前なので、その日のレッスン (無ければ仮) に入る
    await press(env, "action=session_start&kind=practice")
    reply = await env.send_text(TODAY)
    assert reply.splitlines()[0].endswith("11/22 のレッスン（仮）")


async def test_existing_lesson_on_that_date_is_preferred(env: Env):
    await press(env, "action=session_start&kind=lesson")  # id=1 (11/22 のレッスン)
    await press(env, "action=session_end")
    env.clock.advance(hours=1)
    await env.send_text(TODAY)
    assert await env.scalar("SELECT session_id FROM lesson_captures") == 1


async def test_reassign_capture(env: Env):
    await press(env, "action=session_start&kind=practice")  # id=1
    await env.send_text(SAMPLE)  # 10/07 の仮のレッスン id=2
    msg = await press(env, "action=reassign&capture=1")
    assert quick_data(msg) == ["action=reassign_to&capture=1&session=1"]
    assert (await press(env, "action=reassign_to&capture=1&session=1"))["text"] == "📊 計測 #1 を11/22 の練習に入れました。"
    assert await env.scalar("SELECT session_id FROM lesson_captures") == 1
    assert await press(env, "action=reassign_to&capture=1&session=99") == {}


async def test_score_mode_does_not_auto_detect_metrics(env: Env):
    await press(env, "action=mode&mode=score")
    assert (await env.send_text(TODAY)).startswith("🏌 スコアを保存しました")


async def test_image_in_metrics_mode_is_marked(env: Env):
    await press(env, "action=mode&mode=metrics")
    await env.post(env.media_event("image", "i1"))
    assert env.line.reply_texts()[-1].startswith("🖼 計測画像を受け付けました")
    assert await env.scalar("SELECT purpose FROM media") == "metrics"
