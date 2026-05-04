"""Phase 3: session / conversation / message の永続化 (SQLAlchemy 2.0 async)。

EventRepo と engine を共有して同じ DB に書き込む (line bot の他の DB I/O と
同 transaction 上では走らない)。Phase 3 の MVP では消費側 (consultation.py)
から呼び出され、line_user_id 単位のモード状態と会話履歴を保持する。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from .models import ConversationMessageRow, ConversationRow, SessionRow

logger = logging.getLogger(__name__)


MODE_NORMAL = "normal"
MODE_CONSULTING = "consulting"

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_TOOL_USE = "tool_use"
ROLE_TOOL_RESULT = "tool_result"

GAP_ASKED_CLARIFICATION = "asked_clarification"
GAP_OUT_OF_SCOPE = "out_of_scope"
GAP_DATA_MISSING = "data_missing"
GAP_TOOL_ERROR = "tool_error"
GAP_REFUSED = "refused"
GAP_COMPLETED = "completed"


@dataclass(frozen=True)
class Session:
    line_user_id: str
    family_id: str
    mode: str
    consulting_since: str | None
    current_conversation_id: str | None
    updated_at: str


@dataclass(frozen=True)
class Conversation:
    conversation_id: str
    family_id: str
    line_user_id: str
    started_at: str
    ended_at: str | None
    message_count: int
    summary: str | None
    system_prompt_version: str | None
    total_input_tokens: int
    total_output_tokens: int
    total_cache_read_tokens: int


@dataclass(frozen=True)
class ConversationMessage:
    message_id: str
    conversation_id: str
    role: str
    content: str
    created_at: str
    llm_model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    tool_name: str | None = None
    capability_gap: str | None = None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class SessionRepo:
    """SessionRow / ConversationRow / ConversationMessageRow を扱う薄いラッパ。

    EventRepo と engine を共有する想定。`SessionRepo(engine=event_repo.engine)`
    で生成する。
    """

    def __init__(self, *, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    # ----- session (mode) -----

    async def get_mode(self, *, line_user_id: str) -> str:
        """未設定なら MODE_NORMAL を返す (fail-safe)。"""
        async with self._sessionmaker() as session:
            stmt = select(SessionRow.mode).where(SessionRow.line_user_id == line_user_id)
            mode = (await session.execute(stmt)).scalar_one_or_none()
            return mode or MODE_NORMAL

    async def set_mode(self, *, line_user_id: str, family_id: str, mode: str) -> Session:
        """mode を upsert。consulting_since は consulting に切替時のみ更新。"""
        if mode not in {MODE_NORMAL, MODE_CONSULTING}:
            raise ValueError(f"invalid mode: {mode}")
        now = _now_iso()
        async with self._sessionmaker() as session:
            existing = (
                await session.execute(
                    select(SessionRow).where(SessionRow.line_user_id == line_user_id)
                )
            ).scalar_one_or_none()
            if existing is None:
                row = SessionRow(
                    line_user_id=line_user_id,
                    family_id=family_id,
                    mode=mode,
                    consulting_since=now if mode == MODE_CONSULTING else None,
                    current_conversation_id=None,
                    updated_at=now,
                )
                session.add(row)
            else:
                existing.mode = mode
                existing.family_id = family_id
                if mode == MODE_CONSULTING:
                    existing.consulting_since = now
                else:
                    existing.consulting_since = None
                    existing.current_conversation_id = None
                existing.updated_at = now
                row = existing
            await session.commit()
            await session.refresh(row)
            return _to_session(row)

    async def get_session(self, *, line_user_id: str) -> Session | None:
        async with self._sessionmaker() as session:
            row = (
                await session.execute(
                    select(SessionRow).where(SessionRow.line_user_id == line_user_id)
                )
            ).scalar_one_or_none()
            return _to_session(row) if row is not None else None

    # ----- conversation -----

    async def start_conversation(
        self,
        *,
        family_id: str,
        line_user_id: str,
        system_prompt_version: str | None = None,
    ) -> Conversation:
        """新しい conversation を開始 + sessions.current_conversation_id に紐付け。"""
        cid = str(uuid.uuid4())
        now = _now_iso()
        async with self._sessionmaker() as session:
            session.add(
                ConversationRow(
                    conversation_id=cid,
                    family_id=family_id,
                    line_user_id=line_user_id,
                    started_at=now,
                    ended_at=None,
                    message_count=0,
                    summary=None,
                    system_prompt_version=system_prompt_version,
                    total_input_tokens=0,
                    total_output_tokens=0,
                    total_cache_read_tokens=0,
                )
            )
            # sessions.current_conversation_id を更新 (存在しなければ作る)
            existing = (
                await session.execute(
                    select(SessionRow).where(SessionRow.line_user_id == line_user_id)
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    SessionRow(
                        line_user_id=line_user_id,
                        family_id=family_id,
                        mode=MODE_CONSULTING,
                        consulting_since=now,
                        current_conversation_id=cid,
                        updated_at=now,
                    )
                )
            else:
                existing.current_conversation_id = cid
                existing.updated_at = now
            await session.commit()
        return Conversation(
            conversation_id=cid,
            family_id=family_id,
            line_user_id=line_user_id,
            started_at=now,
            ended_at=None,
            message_count=0,
            summary=None,
            system_prompt_version=system_prompt_version,
            total_input_tokens=0,
            total_output_tokens=0,
            total_cache_read_tokens=0,
        )

    async def append_message(
        self,
        *,
        conversation_id: str,
        role: str,
        content: str,
        llm_model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_tokens: int | None = None,
        tool_name: str | None = None,
        capability_gap: str | None = None,
    ) -> ConversationMessage:
        """メッセージを追加し、conversation の message_count / token sums を更新。"""
        now = _now_iso()
        mid = str(uuid.uuid4())
        async with self._sessionmaker() as session:
            session.add(
                ConversationMessageRow(
                    message_id=mid,
                    conversation_id=conversation_id,
                    role=role,
                    content=content,
                    created_at=now,
                    llm_model=llm_model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read_tokens,
                    tool_name=tool_name,
                    capability_gap=capability_gap,
                )
            )
            # conversation の集計値を更新
            await session.execute(
                update(ConversationRow)
                .where(ConversationRow.conversation_id == conversation_id)
                .values(
                    message_count=ConversationRow.message_count + 1,
                    total_input_tokens=ConversationRow.total_input_tokens + (input_tokens or 0),
                    total_output_tokens=ConversationRow.total_output_tokens + (output_tokens or 0),
                    total_cache_read_tokens=ConversationRow.total_cache_read_tokens
                    + (cache_read_tokens or 0),
                )
            )
            await session.commit()
        return ConversationMessage(
            message_id=mid,
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at=now,
            llm_model=llm_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            tool_name=tool_name,
            capability_gap=capability_gap,
        )

    async def fetch_history(
        self, *, conversation_id: str, limit: int = 30
    ) -> list[ConversationMessage]:
        """conversation 内のメッセージを古い順に取得。LLM context 構築用。"""
        async with self._sessionmaker() as session:
            stmt = (
                select(ConversationMessageRow)
                .where(ConversationMessageRow.conversation_id == conversation_id)
                .order_by(ConversationMessageRow.created_at.asc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [_to_message(r) for r in rows]

    async def close_conversation(self, *, conversation_id: str, summary: str | None = None) -> None:
        async with self._sessionmaker() as session:
            await session.execute(
                update(ConversationRow)
                .where(ConversationRow.conversation_id == conversation_id)
                .values(ended_at=_now_iso(), summary=summary)
            )
            await session.commit()


# ---- 内部変換 ----


def _to_session(row: SessionRow) -> Session:
    return Session(
        line_user_id=row.line_user_id,
        family_id=row.family_id,
        mode=row.mode,
        consulting_since=row.consulting_since,
        current_conversation_id=row.current_conversation_id,
        updated_at=row.updated_at,
    )


def _to_message(row: ConversationMessageRow) -> ConversationMessage:
    return ConversationMessage(
        message_id=row.message_id,
        conversation_id=row.conversation_id,
        role=row.role,
        content=row.content,
        created_at=row.created_at,
        llm_model=row.llm_model,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        cache_read_tokens=row.cache_read_tokens,
        tool_name=row.tool_name,
        capability_gap=row.capability_gap,
    )


__all__ = [
    "GAP_ASKED_CLARIFICATION",
    "GAP_COMPLETED",
    "GAP_DATA_MISSING",
    "GAP_OUT_OF_SCOPE",
    "GAP_REFUSED",
    "GAP_TOOL_ERROR",
    "MODE_CONSULTING",
    "MODE_NORMAL",
    "ROLE_ASSISTANT",
    "ROLE_TOOL_RESULT",
    "ROLE_TOOL_USE",
    "ROLE_USER",
    "Conversation",
    "ConversationMessage",
    "Session",
    "SessionRepo",
]
