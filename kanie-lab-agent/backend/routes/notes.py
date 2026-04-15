import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request
from middleware.auth import verify_firebase_token
from google.cloud import firestore as fs_lib
import os

router = APIRouter()


def get_db():
    from google.cloud import firestore
    return firestore.AsyncClient(
        project=os.getenv("FIREBASE_PROJECT_ID", "demo-kanie-lab")
    )


@router.post("/notes")
async def create_note(request: Request, uid: str = Depends(verify_firebase_token)):
    """ノートを作成する"""
    body = await request.json()
    db = get_db()
    note_id = str(uuid.uuid4())
    note_ref = db.collection("users").document(uid).collection("notes").document(note_id)
    await note_ref.set({
        "title": body.get("title", ""),
        "content": body.get("content", ""),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })
    return {"id": note_id, "status": "created"}


@router.get("/notes")
async def list_notes(request: Request, uid: str = Depends(verify_firebase_token)):
    """ノート一覧を取得する"""
    db = get_db()
    notes_ref = (
        db.collection("users")
        .document(uid)
        .collection("notes")
        .order_by("updated_at", direction=fs_lib.Query.DESCENDING)
    )
    docs = await notes_ref.get()
    return {"notes": [{"id": doc.id, **doc.to_dict()} for doc in docs]}


@router.put("/notes/{note_id}")
async def update_note(
    note_id: str,
    request: Request,
    uid: str = Depends(verify_firebase_token),
):
    """ノートを更新する"""
    body = await request.json()
    db = get_db()
    note_ref = db.collection("users").document(uid).collection("notes").document(note_id)
    await note_ref.update({
        "title": body.get("title", ""),
        "content": body.get("content", ""),
        "updated_at": datetime.now(timezone.utc),
    })
    return {"id": note_id, "status": "updated"}


@router.delete("/notes/{note_id}")
async def delete_note(
    note_id: str,
    request: Request,
    uid: str = Depends(verify_firebase_token),
):
    """ノートを削除する"""
    db = get_db()
    note_ref = db.collection("users").document(uid).collection("notes").document(note_id)
    await note_ref.delete()
    return {"id": note_id, "status": "deleted"}
