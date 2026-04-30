"""ユーザーから来たテキストメッセージをコマンドにルーティングするロジック。

Phase 1 ではテキストコマンドのみで成立させ、Rich Menu の Postback Action は
Phase 2 で対応する（同じハンドラ関数群を `dispatch_postback` から呼べるよう設計）。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.handlers.disclaimer import (
    DELETE_CONFIRMATION,
    DISCLAIMER_FOOTER,
    HELP_TEXT,
)
from app.instrumentation.events import (
    EVENT_MODE_SWITCHED,
    EVENT_QUIZ_ANSWERED,
    EVENT_QUIZ_STARTED,
    EVENT_USER_DATA_DELETED,
    emit_business_event,
)
from app.models import Goal, QuizMode, UserStatus
from app.repositories.protocols import (
    AnswerHistoryRepo,
    LineUserIndexRepo,
    SessionRepo,
    UserRepo,
)
from app.repositories.question_pool import QuestionPoolLike
from app.services.identity import IdentityService
from app.services.quiz_service import QuizService
from app.services.scoring import ScoringService

logger = logging.getLogger(__name__)


# ---- ユーザー入力の正規化 / 判定 ----

_QUIZ_KEYWORDS = {"クイズ", "出題", "問題"}
_HELP_KEYWORDS = {"ヘルプ", "help", "使い方", "?", "？"}
_MODE_INFO_KEYWORDS = {"現在のモード", "モード"}
_MODE_SWITCH_KEYWORDS = {"モード切替", "モード切り替え", "切替"}
_PROVISIONAL_KEYWORDS = {"仮免", "仮免許", "provisional"}
_FULL_KEYWORDS = {"本免", "本免許", "full"}
_DELETE_KEYWORDS = {"データを削除", "削除", "退会"}
_TRUE_KEYWORDS = {"正しい", "○", "〇", "true", "1"}
_FALSE_KEYWORDS = {"誤り", "×", "false", "2"}


def _normalize(text: str) -> str:
    """テキストを strip + lower に正規化（コマンドキーワード照合の単一基準）。"""
    return text.strip().lower()


def _looks_numeric_answer(text: str) -> int | None:
    """『1』『2』のような数字回答を choice index に変換。"""
    m = re.fullmatch(r"\s*(\d+)\s*", text)
    if not m:
        return None
    n = int(m.group(1))
    if n < 1:
        return None
    return n - 1  # 1-indexed → 0-indexed


@dataclass
class HandlerDeps:
    users: UserRepo
    line_user_index: LineUserIndexRepo
    sessions: SessionRepo
    answer_histories: AnswerHistoryRepo
    pool: QuestionPoolLike

    @property
    def identity(self) -> IdentityService:
        return IdentityService(self.users, self.line_user_index)

    @property
    def quiz(self) -> QuizService:
        return QuizService(self.pool, self.sessions, self.answer_histories)

    @property
    def scoring(self) -> ScoringService:
        return ScoringService(self.answer_histories)


class CommandRouter:
    """`dispatch_text` を呼ぶと、コマンド種別に応じた応答テキストのリストを返す。"""

    def __init__(self, deps: HandlerDeps) -> None:
        self._deps = deps

    async def dispatch_text(
        self,
        *,
        line_user_id: str,
        text: str,
        bot_channel_id: str = "",
        display_name: str | None = None,
    ) -> list[str]:
        """テキストメッセージを受けて、応答テキスト（最大 5 通）を返す。"""
        # キーワードはすべて小文字で定義しているため、`_normalize` で
        # 大文字小文字を吸収する単一基準にまとめる（日本語は影響を受けない）。
        key = _normalize(text)

        user = await self._deps.identity.get_or_create(
            line_user_id,
            bot_channel_id=bot_channel_id,
            display_name=display_name,
        )
        if user.status is not UserStatus.ACTIVE:
            return [
                "現在お客様のデータは削除予定の状態です。"
                "再度ご利用される場合はサポートまでご連絡ください。"
            ]

        # 1. データ削除（最優先：誤動作リスクを下げるため）
        if key in _DELETE_KEYWORDS:
            return await self._handle_delete(user.internal_uid)

        # 2. ヘルプ
        if key in _HELP_KEYWORDS:
            return [HELP_TEXT]

        # 3. モード関連
        if key in _MODE_INFO_KEYWORDS:
            return [_format_current_mode(user.active_goal)]
        if key in _MODE_SWITCH_KEYWORDS:
            return await self._handle_mode_toggle(user.internal_uid, user.active_goal)
        if key in _PROVISIONAL_KEYWORDS:
            return await self._handle_mode_set(user.internal_uid, Goal.PROVISIONAL)
        if key in _FULL_KEYWORDS:
            return await self._handle_mode_set(user.internal_uid, Goal.FULL)

        # 4. クイズ開始
        if key in _QUIZ_KEYWORDS:
            return await self._handle_quiz_start(user.internal_uid, user.active_goal)

        # 5. 出題中の回答
        active = await self._deps.sessions.get_active(user.internal_uid)
        if active is not None:
            chosen = _parse_answer(key)
            if chosen is not None:
                return await self._handle_answer(user.internal_uid, chosen)

        # 6. 不明
        return [
            "コマンドが認識できませんでした。\n"
            "「クイズ」「ヘルプ」「モード切替」「データを削除」が使えます。"
        ]

    # ---- private ----

    async def _handle_quiz_start(
        self, internal_uid: str, goal: Goal
    ) -> list[str]:
        result = await self._deps.quiz.start_question(
            internal_uid=internal_uid,
            goal=goal.value,
            mode=QuizMode.MINI,
        )
        if result is None:
            return ["現在出題できる問題がありません。しばらく経ってから再度お試しください。"]
        question, session = result
        emit_business_event(
            event_name=EVENT_QUIZ_STARTED,
            properties={
                "question_id": question.id,
                "question_version": question.version,
                "goal": goal.value,
                "category": question.category,
                "difficulty": question.difficulty,
                "mode": session.mode.value,
            },
            user_id=internal_uid,
            session_id=session.session_id,
        )
        return [_format_question(question, goal)]

    async def _handle_answer(
        self, internal_uid: str, chosen_index: int
    ) -> list[str]:
        consumed = await self._deps.quiz.consume_active_session(internal_uid)
        if consumed is None:
            return ["出題中の問題がありません。「クイズ」と送って次の問題を始めてください。"]
        session, question = consumed
        if chosen_index >= len(question.choices):
            return [
                f"選択肢の番号が範囲外です（1〜{len(question.choices)} の範囲で）。"
            ]
        scoring = await self._deps.scoring.grade_and_record(
            internal_uid=internal_uid,
            question=question,
            chosen_index=chosen_index,
        )
        emit_business_event(
            event_name=EVENT_QUIZ_ANSWERED,
            properties={
                "question_id": question.id,
                "question_version": question.version,
                "answer": chosen_index,
                "correct": scoring.correct,
                "category": question.category,
                "difficulty": question.difficulty,
            },
            user_id=internal_uid,
            session_id=session.session_id,
        )
        return [_format_scoring(question, scoring)]

    async def _handle_mode_toggle(
        self, internal_uid: str, current: Goal
    ) -> list[str]:
        new_goal = Goal.FULL if current is Goal.PROVISIONAL else Goal.PROVISIONAL
        await self._deps.identity.switch_goal(internal_uid, new_goal)
        emit_business_event(
            event_name=EVENT_MODE_SWITCHED,
            properties={"from_goal": current.value, "to_goal": new_goal.value},
            user_id=internal_uid,
        )
        return [
            f"モードを切替えました：{_goal_jp(current)} → {_goal_jp(new_goal)}\n"
            "「クイズ」と送ると新しいモードで出題されます。"
        ]

    async def _handle_mode_set(
        self, internal_uid: str, goal: Goal
    ) -> list[str]:
        user = await self._deps.identity.switch_goal(internal_uid, goal)
        if user is None:
            return ["モード変更に失敗しました。再度お試しください。"]
        emit_business_event(
            event_name=EVENT_MODE_SWITCHED,
            properties={"from_goal": None, "to_goal": goal.value},
            user_id=internal_uid,
        )
        return [
            f"モードを「{_goal_jp(goal)}」に設定しました。\n"
            "「クイズ」と送ると新しいモードで出題されます。"
        ]

    async def _handle_delete(self, internal_uid: str) -> list[str]:
        user = await self._deps.users.get(internal_uid)
        if user is None:
            return [DELETE_CONFIRMATION]
        # 即時論理削除 → 7 日後物理削除（Phase 1 は in-memory のため同期 4 操作で完結）。
        # TODO(Phase 2): Firestore 移行時は batch write / transaction で原子化し、
        #                途中失敗時に index だけ残るケースを排除する。
        await self._deps.line_user_index.delete(user.line_user_id)
        await self._deps.sessions.delete_all(internal_uid)
        await self._deps.answer_histories.delete_all(internal_uid)
        scheduled = user.model_copy(
            update={
                "status": UserStatus.SCHEDULED_DELETION,
                "scheduled_deletion_at": datetime.now(UTC) + timedelta(days=7),
            }
        )
        await self._deps.users.upsert(scheduled)
        emit_business_event(
            event_name=EVENT_USER_DATA_DELETED,
            properties={"trigger": "user_command"},
            user_id=internal_uid,
        )
        return [DELETE_CONFIRMATION]


# ---- formatters ----

def _format_question(question, goal: Goal) -> str:  # noqa: ANN001 (model)
    lines = [
        f"【{_goal_jp(goal)} / {_category_jp(question.category)}】",
        question.body,
        "",
    ]
    for c in question.choices:
        lines.append(f"{c.index + 1}. {c.text}")
    lines.append("")
    lines.append("回答は番号（例: 1）または「正しい」「誤り」で送ってください。")
    return "\n".join(lines)


def _format_scoring(question, scoring) -> str:  # noqa: ANN001 (NamedTuple)
    head = "✅ 正解です！" if scoring.correct else "❌ 不正解です。"
    correct_choice = question.choices[question.correct].text
    lines = [
        head,
        f"あなたの回答: {scoring.chosen_index + 1}",
        f"正解: {scoring.correct_index + 1}（{correct_choice}）",
        "",
        "▼ 解説",
        scoring.explanation,
        "",
        "▼ 根拠",
    ]
    for src in question.sources:
        lines.append(f"・{src.title}")
        lines.append(f"  {src.url}")
    lines.append("")
    lines.append(DISCLAIMER_FOOTER)
    return "\n".join(lines)


def _format_current_mode(goal: Goal) -> str:
    return f"現在のモード：{_goal_jp(goal)}\n「モード切替」と送ると変更できます。"


def _goal_jp(goal: Goal) -> str:
    return "仮免" if goal is Goal.PROVISIONAL else "本免"


def _category_jp(cat: str) -> str:
    return {
        "signs": "標識",
        "rules": "交通ルール",
        "manners": "運転マナー",
        "hazard": "危険予測",
    }.get(cat, cat)


def _parse_answer(text: str) -> int | None:
    """ユーザー入力を choice index（0-indexed）に変換。"""
    n = _looks_numeric_answer(text)
    if n is not None:
        return n
    if text in _TRUE_KEYWORDS:
        return 0  # 「正しい」は index 0
    if text in _FALSE_KEYWORDS:
        return 1  # 「誤り」は index 1
    return None


# ---- module-level helper for tests / DI ----

async def dispatch_text(
    deps: HandlerDeps,
    *,
    line_user_id: str,
    text: str,
    bot_channel_id: str = "",
    display_name: str | None = None,
) -> list[str]:
    return await CommandRouter(deps).dispatch_text(
        line_user_id=line_user_id,
        text=text,
        bot_channel_id=bot_channel_id,
        display_name=display_name,
    )


__all__ = ["CommandRouter", "HandlerDeps", "dispatch_text"]
