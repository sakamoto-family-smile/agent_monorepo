"""リポジトリの Protocol 定義（Firestore / in-memory どちらも実装する）。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.models import AnswerHistory, Session, User


@runtime_checkable
class UserRepo(Protocol):
    async def get(self, internal_uid: str) -> User | None: ...
    async def upsert(self, user: User) -> None: ...
    async def delete(self, internal_uid: str) -> None: ...


@runtime_checkable
class LineUserIndexRepo(Protocol):
    """LINE User ID → internal_uid の逆引き。

    DESIGN.md §8.2 の `/line_user_index/{line_user_id}` に対応。
    """

    async def get_internal_uid(self, line_user_id: str) -> str | None: ...
    async def set_mapping(
        self, line_user_id: str, internal_uid: str, bot_channel_id: str = ""
    ) -> None: ...
    async def delete(self, line_user_id: str) -> None: ...


@runtime_checkable
class SessionRepo(Protocol):
    async def get(self, internal_uid: str, session_id: str) -> Session | None: ...
    async def get_active(self, internal_uid: str) -> Session | None: ...
    async def upsert(self, session: Session) -> None: ...
    async def delete_all(self, internal_uid: str) -> None: ...


@runtime_checkable
class AnswerHistoryRepo(Protocol):
    async def get(self, internal_uid: str, question_id: str) -> AnswerHistory | None: ...
    async def upsert(self, history: AnswerHistory) -> None: ...
    async def list_recent(
        self, internal_uid: str, limit: int = 20
    ) -> list[AnswerHistory]: ...
    async def delete_all(self, internal_uid: str) -> None: ...


class RepoBundle(Protocol):
    """4 リポジトリをまとめて DI するためのバンドル。"""

    users: UserRepo
    line_user_index: LineUserIndexRepo
    sessions: SessionRepo
    answer_histories: AnswerHistoryRepo
