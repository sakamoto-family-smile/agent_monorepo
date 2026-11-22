"""入力モード・リッチメニューのボタン・セッションの開始と終了・コース名・スコア (§4.3.1)。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.conftest import Env

RICHMENU = Path(__file__).resolve().parents[1] / "config" / "richmenu" / "richmenu.json"


async def press(env: Env, data: str) -> dict[str, Any]:
    """ボタンを押し、返ってきた reply の 1 件目を返す。"""
    before = len(env.line.replies)
    res = await env.post(env.postback_event(data))
    assert res.status_code == 200
    new = env.line.replies[before:]
    return new[0][1][0] if new else {}


def quick_data(msg: dict[str, Any]) -> list[str]:
    return [i["action"]["data"] for i in msg.get("quickReply", {}).get("items", [])]


def test_richmenu_definition_matches_handlers():
    from app.handlers.postback import HANDLERS

    menu = json.loads(RICHMENU.read_text(encoding="utf-8"))
    assert menu["size"] == {"width": 2500, "height": 1686} and len(menu["areas"]) == 6
    covered = sum(a["bounds"]["width"] * a["bounds"]["height"] for a in menu["areas"])
    assert covered == 2500 * 1686
    for area in menu["areas"]:
        action = dict(p.split("=") for p in area["action"]["data"].split("&"))["action"]
        assert action in HANDLERS
        assert len(area["action"]["label"]) <= 20


async def test_session_start_and_end_with_summary(env: Env):
    msg = await press(env, "action=session")
    assert quick_data(msg) == [
        "action=session_start&kind=practice",
        "action=session_start&kind=lesson",
        "action=session_start&kind=round",
    ]
    assert (await press(env, "action=session_start&kind=lesson"))["text"] == "▶ レッスンを開始しました ｜ 11/22 のレッスン"
    assert await env.send_text("フェースが開く") == "📝 メモを保存しました ｜ 11/22 のレッスン"

    msg = await press(env, "action=session")
    assert msg["text"].startswith("▶ 11/22 のレッスン中です") and "action=session_end" in quick_data(msg)
    msg = await press(env, "action=session_end")
    assert msg["text"] == "⏹ 11/22 のレッスンを終了しました（メモ 1・動画/画像 0・計測 0・スコア 0）。"
    row = (await env.rows("SELECT end_reason, ended_at FROM sessions WHERE kind = 'lesson'"))[0]
    assert row["end_reason"] == "manual" and row["ended_at"]
    assert (await env.send_text("終わったあと")).endswith("11/22 の練習（仮）")


async def test_starting_again_ends_the_previous_session(env: Env):
    await press(env, "action=session_start&kind=practice")
    await press(env, "action=session_start&kind=lesson")
    rows = await env.rows("SELECT kind, end_reason FROM sessions ORDER BY id")
    assert rows == [{"kind": "practice", "end_reason": "manual"}, {"kind": "lesson", "end_reason": None}]


async def test_text_end_command_clears_mode_and_session(env: Env):
    await press(env, "action=session_start&kind=practice")
    await press(env, "action=mode&mode=score")
    assert (await env.send_text("終了")).startswith("⏹ 11/22 の練習を終了しました")
    assert await env.scalar("SELECT count(*) FROM input_modes") == 0
    assert (await env.send_text("終了")).startswith("⏹ 入力モードを解除しました")


async def test_round_course_by_text_then_by_quick_reply(env: Env):
    msg = await press(env, "action=session_start&kind=round")
    assert "コース名を送ってください" in msg["text"] and "コース名の入力" in msg["text"]
    assert "quickReply" not in msg  # まだコースがない
    assert (await env.send_text("湘南 カントリークラブ")).startswith("⏹") is False
    assert await env.scalar("SELECT name FROM courses") == "湘南 カントリークラブ"
    assert await env.scalar("SELECT course_id FROM sessions WHERE kind = 'round'") == 1
    assert await env.scalar("SELECT count(*) FROM memos") == 0  # コース名はメモにしない

    env.clock.advance(days=7)
    msg = await press(env, "action=session_start&kind=round")
    assert quick_data(msg) == ["action=course&session=2&course=1"]
    reply = await press(env, "action=course&session=2&course=1")
    assert reply["text"].startswith("⛳ コースを「湘南 カントリークラブ」にしました")
    assert await env.scalar("SELECT count(*) FROM input_modes") == 0


async def test_course_name_variants_are_merged(env: Env):
    await press(env, "action=session_start&kind=round")
    await env.send_text("湘南カントリークラブ")
    await press(env, "action=session_start&kind=round")
    await env.send_text("湘南　カントリー　クラブ")  # 全角空白
    assert await env.scalar("SELECT count(*) FROM courses") == 1
    assert json.loads(await env.scalar("SELECT aliases_json FROM courses")) == ["湘南 カントリー クラブ"]


async def test_score_mode_saves_raw_text_and_expires(env: Env):
    msg = await press(env, "action=mode&mode=score")
    assert "スコアを送ってください" in msg["text"]
    reply = await env.send_text("92 パット34 FW7/14 パーオン5")
    assert reply == "🏌 スコアを保存しました（集計は今後の更新で行います） ｜ スコアモード・11/22 の練習（仮）"
    assert await env.scalar("SELECT text FROM score_texts") == "92 パット34 FW7/14 パーオン5"

    # 送るたびに延びる。最後の操作から 30 分で切れる
    env.clock.advance(minutes=29)
    await env.send_text("後半 45")
    env.clock.advance(minutes=29)
    assert (await env.send_text("まだスコア")).startswith("🏌")
    env.clock.advance(minutes=30)
    assert (await env.send_text("もうメモ")).startswith("📝 メモを保存しました ｜ 11/22 の練習（仮）")
    assert await env.scalar("SELECT count(*) FROM input_modes") == 0
    assert (await env.send_text("取消")).startswith("↩️ 直前のメモ")
    assert (await env.send_text("取消")).startswith("↩️ 直前のスコア")


async def test_memo_button_clears_mode(env: Env):
    await press(env, "action=mode&mode=score")
    assert (await press(env, "action=mode&mode=memo"))["text"].startswith("📝 メモモードです")
    assert (await env.send_text("ふつうのメモ")).startswith("📝")


async def test_video_mode_tags_following_videos(env: Env):
    msg = await press(env, "action=mode&mode=video")
    assert quick_data(msg) == ["action=video_angle&angle=dtl", "action=video_angle&angle=face_on"]
    msg = await press(env, "action=video_angle&angle=dtl")
    assert len(quick_data(msg)) == 13 and quick_data(msg)[6] == "action=video_club&angle=dtl&club=7I"
    msg = await press(env, "action=video_club&angle=dtl&club=7I")
    assert "後方・7I" in msg["text"] and "動画モード" in msg["text"]

    await env.post(env.media_event("video", "v1"))
    await env.post(env.media_event("video", "v2"))
    assert env.line.reply_texts()[-1].startswith("🎥 動画を受け付けました（後方・7I）")
    rows = await env.rows("SELECT angle, club FROM media ORDER BY id")
    assert rows == [{"angle": "dtl", "club": "7I"}] * 2
    # テキストはメモのまま (モードは続く)
    assert (await env.send_text("テイクバックが速い")).startswith("📝 メモを保存しました ｜ 動画モード")


async def test_video_mode_without_club(env: Env):
    await press(env, "action=video_club&angle=face_on&club=none")
    await env.post(env.media_event("video", "v1"))
    assert (await env.rows("SELECT angle, club FROM media"))[0] == {"angle": "face_on", "club": None}


async def test_video_without_mode_asks_angle_then_club(env: Env):
    await env.post(env.media_event("video", "v1"))
    msg = env.line.replies[-1][1][0]
    assert quick_data(msg) == ["action=tag&media=1&angle=dtl", "action=tag&media=1&angle=face_on"]
    msg = await press(env, "action=tag&media=1&angle=face_on")
    assert "action=tag&media=1&club=SW" in quick_data(msg)
    assert len(quick_data(msg)) <= 13
    await press(env, "action=tag&media=1&club=SW")
    assert (await env.rows("SELECT angle, club FROM media"))[0] == {"angle": "face_on", "club": "SW"}


async def test_image_without_mode_asks_purpose(env: Env):
    await env.post(env.media_event("image", "i1"))
    msg = env.line.replies[-1][1][0]
    assert quick_data(msg) == ["action=tag&media=1&purpose=metrics", "action=tag&media=1&purpose=other"]
    assert (await press(env, "action=tag&media=1&purpose=metrics"))["text"] == "🖼 #1 を計測画像にしました。"
    assert await env.scalar("SELECT purpose FROM media") == "metrics"


async def test_tag_rejects_wrong_kind_and_bad_values(env: Env):
    await env.post(env.media_event("image", "i1"))
    assert await press(env, "action=tag&media=1&angle=dtl") == {}  # 画像にアングルは付けない
    assert await press(env, "action=tag&media=1&purpose=evil") == {}
    assert await press(env, "action=tag&media=abc&purpose=other") == {}
    assert await press(env, "action=tag&media=99&purpose=other") == {}
    assert await press(env, "action=video_club&angle=dtl&club=DROP TABLE") == {}
    assert await press(env, "action=unknown") == {}
    assert await env.scalar("SELECT angle IS NULL AND purpose IS NULL FROM media") == 1


async def test_ask_is_not_ready_yet(env: Env):
    assert "準備中" in (await press(env, "action=mode&mode=ask"))["text"]
    assert "準備中" in await env.send_text("? 最近のドライバーの課題は？")
    assert await env.scalar("SELECT count(*) FROM memos") == 0
