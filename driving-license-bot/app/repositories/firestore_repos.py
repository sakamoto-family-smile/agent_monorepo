"""Firestore リポジトリ実装。

`app.repositories.protocols` の Protocol を満たすため、handler / service 層は
in-memory ↔ Firestore の差し替えで無変更。Phase 1.5 の核となるインフラ層。

Collection 構造（DESIGN.md §8.2 と整合）:
- /users/{internal_uid}
- /users/{internal_uid}/sessions/{session_id}
- /users/{internal_uid}/answer_history/{question_id}
- /line_user_index/{line_user_id}
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from google.cloud.firestore_v1 import AsyncClient
from google.cloud.firestore_v1.async_query import AsyncQuery
from google.cloud.firestore_v1.base_query import FieldFilter

from app.models import AnswerHistory, Question, Session, SessionState, User

# 親 collection 名はここで一元管理（DESIGN.md §8.2）。
USERS_COLLECTION = "users"
LINE_USER_INDEX_COLLECTION = "line_user_index"
SESSIONS_SUBCOLLECTION = "sessions"
ANSWER_HISTORY_SUBCOLLECTION = "answer_history"
QUESTIONS_COLLECTION = "questions"  # Phase 2-C2: 問題本文 (Question pydantic)


def _serialize(model: Any) -> dict[str, Any]:
    """pydantic v2 モデルを Firestore に書き込める dict に変換。

    `mode="json"` で datetime / Enum を ISO8601 / str に変換する。Firestore は
    datetime を native に持てるが、ISO 文字列にしておくほうが BigQuery エクス
    ポート時にも扱いやすい。"""
    return model.model_dump(mode="json")


def _deserialize_user(data: dict[str, Any]) -> User:
    return User.model_validate(data)


def _deserialize_session(data: dict[str, Any]) -> Session:
    return Session.model_validate(data)


def _deserialize_answer_history(data: dict[str, Any]) -> AnswerHistory:
    return AnswerHistory.model_validate(data)


class FirestoreUserRepo:
    def __init__(self, client: AsyncClient) -> None:
        self._coll = client.collection(USERS_COLLECTION)

    async def get(self, internal_uid: str) -> User | None:
        snap = await self._coll.document(internal_uid).get()
        if not snap.exists:
            return None
        return _deserialize_user(snap.to_dict() or {})

    async def upsert(self, user: User) -> None:
        await self._coll.document(user.internal_uid).set(_serialize(user))

    async def delete(self, internal_uid: str) -> None:
        await self._coll.document(internal_uid).delete()


class FirestoreLineUserIndexRepo:
    def __init__(self, client: AsyncClient) -> None:
        self._coll = client.collection(LINE_USER_INDEX_COLLECTION)

    async def get_internal_uid(self, line_user_id: str) -> str | None:
        snap = await self._coll.document(line_user_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        uid = data.get("internal_uid")
        return uid if isinstance(uid, str) and uid else None

    async def set_mapping(
        self, line_user_id: str, internal_uid: str, bot_channel_id: str = ""
    ) -> None:
        await self._coll.document(line_user_id).set(
            {
                "internal_uid": internal_uid,
                "bot_channel_id": bot_channel_id,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )

    async def delete(self, line_user_id: str) -> None:
        await self._coll.document(line_user_id).delete()


class FirestoreSessionRepo:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client
        self._users_coll = client.collection(USERS_COLLECTION)

    def _subcoll(self, internal_uid: str):  # noqa: ANN202 — Firestore client type
        return self._users_coll.document(internal_uid).collection(
            SESSIONS_SUBCOLLECTION
        )

    async def get(self, internal_uid: str, session_id: str) -> Session | None:
        snap = await self._subcoll(internal_uid).document(session_id).get()
        if not snap.exists:
            return None
        return _deserialize_session(snap.to_dict() or {})

    async def get_active(self, internal_uid: str) -> Session | None:
        query: AsyncQuery = (
            self._subcoll(internal_uid)
            .where(filter=FieldFilter("state", "==", SessionState.AWAITING_ANSWER.value))
            .limit(1)
        )
        async for doc in query.stream():
            data = doc.to_dict() or {}
            return _deserialize_session(data)
        return None

    async def upsert(self, session: Session) -> None:
        await self._subcoll(session.internal_uid).document(session.session_id).set(
            _serialize(session)
        )

    async def delete_all(self, internal_uid: str) -> None:
        # Firestore では subcollection の一括削除は管理者 API のみのため、
        # アプリ側で stream → delete でループする（Phase 1 ではセッション数は
        # 1 ユーザー当たり数件想定）。
        async for doc in self._subcoll(internal_uid).stream():
            await doc.reference.delete()


class FirestoreAnswerHistoryRepo:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client
        self._users_coll = client.collection(USERS_COLLECTION)

    def _subcoll(self, internal_uid: str):  # noqa: ANN202
        return self._users_coll.document(internal_uid).collection(
            ANSWER_HISTORY_SUBCOLLECTION
        )

    async def get(
        self, internal_uid: str, question_id: str
    ) -> AnswerHistory | None:
        snap = await self._subcoll(internal_uid).document(question_id).get()
        if not snap.exists:
            return None
        return _deserialize_answer_history(snap.to_dict() or {})

    async def upsert(self, history: AnswerHistory) -> None:
        await self._subcoll(history.internal_uid).document(history.question_id).set(
            _serialize(history)
        )

    async def list_recent(
        self, internal_uid: str, limit: int = 20
    ) -> list[AnswerHistory]:
        query: AsyncQuery = (
            self._subcoll(internal_uid)
            .order_by("last_answered_at", direction="DESCENDING")
            .limit(limit)
        )
        results: list[AnswerHistory] = []
        async for doc in query.stream():
            results.append(_deserialize_answer_history(doc.to_dict() or {}))
        return results

    async def delete_all(self, internal_uid: str) -> None:
        async for doc in self._subcoll(internal_uid).stream():
            await doc.reference.delete()


class FirestoreQuestionRepo:
    """Phase 2-C2: 問題本文 (Question pydantic) を Firestore に保存。

    pgvector の StoredQuestion (dedup メタ + embedding) と分離する設計。
    レビュー UI が `/questions/{id}` で本文を取得する。
    """

    def __init__(self, client: AsyncClient) -> None:
        self._coll = client.collection(QUESTIONS_COLLECTION)

    async def upsert(self, question: Question) -> None:
        await self._coll.document(question.id).set(_serialize(question))

    async def get(self, question_id: str) -> Question | None:
        snap = await self._coll.document(question_id).get()
        if not snap.exists:
            return None
        return Question.model_validate(snap.to_dict() or {})

    async def delete(self, question_id: str) -> None:
        await self._coll.document(question_id).delete()


__all__ = [
    "FirestoreAnswerHistoryRepo",
    "FirestoreLineUserIndexRepo",
    "FirestoreQuestionRepo",
    "FirestoreSessionRepo",
    "FirestoreUserRepo",
]
