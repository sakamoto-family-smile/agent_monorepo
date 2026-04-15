"""
セッション・メッセージのストレージサービス。
Firestoreエミュレーター（Java必須）の代わりにインメモリストアを使用する。
本番環境では google-cloud-firestore に差し替える。
"""
import os
from datetime import datetime, timezone
from collections import defaultdict
from typing import Any

# --------------------------------------------------------------------------
# インメモリストア
# _store[uid][session_id] = {meta: {...}, messages: [...]}
# --------------------------------------------------------------------------
_store: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)


async def save_message(uid: str, session_id: str, role: str, content: str):
    """メッセージをストアに保存する"""
    if session_id not in _store[uid]:
        _store[uid][session_id] = {
            "meta": {
                "title": "新しい会話",
                "mode": "research",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            "messages": [],
        }
    _store[uid][session_id]["messages"].append({
        "id": f"{role}_{len(_store[uid][session_id]['messages'])}",
        "role": role,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    _store[uid][session_id]["meta"]["updated_at"] = datetime.now(timezone.utc).isoformat()


async def create_or_update_session(uid: str, session_id: str, title: str, mode: str):
    """セッションを作成または更新する"""
    if session_id not in _store[uid]:
        _store[uid][session_id] = {
            "meta": {
                "title": title,
                "mode": mode,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            "messages": [],
        }
    else:
        _store[uid][session_id]["meta"]["updated_at"] = datetime.now(timezone.utc).isoformat()
        if title:
            _store[uid][session_id]["meta"]["title"] = title


async def get_sessions(uid: str):
    """ユーザーのセッション一覧を取得する（最新50件）"""
    sessions = []
    for session_id, data in _store[uid].items():
        sessions.append({"id": session_id, **data["meta"]})
    sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    return sessions[:50]


async def get_session_messages(uid: str, session_id: str):
    """セッションのメッセージ一覧を取得する"""
    if session_id not in _store[uid]:
        return []
    return _store[uid][session_id]["messages"]


async def delete_session(uid: str, session_id: str):
    """セッションを削除する"""
    _store[uid].pop(session_id, None)
