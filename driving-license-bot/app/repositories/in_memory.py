"""in-memory リポジトリ実装（Phase 1 のテスト・ローカル動作用）。

Phase 2 で Firestore 実装に差し替えるが、Protocol を満たす同一インタフェースで
DI 可能なため、ハンドラ層・サービス層は無変更。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models import AnswerHistory, Session, SessionState, User


class InMemoryUserRepo:
    def __init__(self) -> None:
        self._users: dict[str, User] = {}

    async def get(self, internal_uid: str) -> User | None:
        return self._users.get(internal_uid)

    async def upsert(self, user: User) -> None:
        self._users[user.internal_uid] = user

    async def delete(self, internal_uid: str) -> None:
        self._users.pop(internal_uid, None)


class InMemoryLineUserIndexRepo:
    def __init__(self) -> None:
        self._index: dict[str, dict[str, str]] = {}

    async def get_internal_uid(self, line_user_id: str) -> str | None:
        entry = self._index.get(line_user_id)
        return entry["internal_uid"] if entry else None

    async def set_mapping(
        self, line_user_id: str, internal_uid: str, bot_channel_id: str = ""
    ) -> None:
        self._index[line_user_id] = {
            "internal_uid": internal_uid,
            "bot_channel_id": bot_channel_id,
        }

    async def delete(self, line_user_id: str) -> None:
        self._index.pop(line_user_id, None)


class InMemorySessionRepo:
    def __init__(self) -> None:
        # (internal_uid, session_id) → Session
        self._sessions: dict[tuple[str, str], Session] = {}

    async def get(self, internal_uid: str, session_id: str) -> Session | None:
        return self._sessions.get((internal_uid, session_id))

    async def get_active(self, internal_uid: str) -> Session | None:
        """`AWAITING_ANSWER` 状態のセッションを 1 件返す（Phase 1 では同時 1 件想定）。"""
        for (uid, _), sess in self._sessions.items():
            if uid == internal_uid and sess.state is SessionState.AWAITING_ANSWER:
                return sess
        return None

    async def upsert(self, session: Session) -> None:
        self._sessions[(session.internal_uid, session.session_id)] = session

    async def delete_all(self, internal_uid: str) -> None:
        keys = [k for k in self._sessions if k[0] == internal_uid]
        for k in keys:
            self._sessions.pop(k, None)


class InMemoryAnswerHistoryRepo:
    def __init__(self) -> None:
        self._histories: dict[tuple[str, str], AnswerHistory] = {}

    async def get(
        self, internal_uid: str, question_id: str
    ) -> AnswerHistory | None:
        return self._histories.get((internal_uid, question_id))

    async def upsert(self, history: AnswerHistory) -> None:
        self._histories[(history.internal_uid, history.question_id)] = history

    async def list_recent(
        self, internal_uid: str, limit: int = 20
    ) -> list[AnswerHistory]:
        items = [
            h for (uid, _), h in self._histories.items() if uid == internal_uid
        ]
        items.sort(key=lambda h: h.last_answered_at, reverse=True)
        return items[:limit]

    async def delete_all(self, internal_uid: str) -> None:
        keys = [k for k in self._histories if k[0] == internal_uid]
        for k in keys:
            self._histories.pop(k, None)


@dataclass
class InMemoryRepoBundle:
    users: InMemoryUserRepo = field(default_factory=InMemoryUserRepo)
    line_user_index: InMemoryLineUserIndexRepo = field(
        default_factory=InMemoryLineUserIndexRepo
    )
    sessions: InMemorySessionRepo = field(default_factory=InMemorySessionRepo)
    answer_histories: InMemoryAnswerHistoryRepo = field(
        default_factory=InMemoryAnswerHistoryRepo
    )
