from fastapi import APIRouter, Depends, HTTPException, Request
from middleware.auth import verify_firebase_token
from services import firestore as fs

router = APIRouter()


@router.get("/sessions")
async def list_sessions(request: Request, uid: str = Depends(verify_firebase_token)):
    """セッション一覧を取得する"""
    sessions = await fs.get_sessions(uid)
    return {"sessions": sessions}


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    request: Request,
    uid: str = Depends(verify_firebase_token),
):
    """特定セッションのメッセージ一覧を取得する"""
    messages = await fs.get_session_messages(uid, session_id)
    return {"session_id": session_id, "messages": messages}


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    request: Request,
    uid: str = Depends(verify_firebase_token),
):
    """セッションを削除する"""
    await fs.delete_session(uid, session_id)
    return {"status": "deleted", "session_id": session_id}
