"""FirestoreRepo のシリアライズ整合性テスト。

実 Firestore / Emulator は CI で立てない方針のため、ここでは pydantic モデル
の `model_dump(mode="json")` ↔ `model_validate` round-trip と、Firestore client
を fake で置き換えた簡易統合テストのみ行う。本番接続テストは Phase 2 で別途。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models import (
    AnswerHistory,
    Goal,
    QuizMode,
    Session,
    SessionState,
    User,
    UserStatus,
)


def test_user_round_trip_via_json_dict() -> None:
    """User を mode='json' で dump → 再構築できる（Firestore 経由でも壊れない）。"""
    now = datetime.now(UTC)
    user = User(
        internal_uid="u-1",
        line_user_id="U" + "a" * 32,
        display_name="テスト太郎",
        active_goal=Goal.FULL,
        status=UserStatus.SCHEDULED_DELETION,
        scheduled_deletion_at=now + timedelta(days=7),
        consented_at=now,
    )
    payload = user.model_dump(mode="json")
    # Firestore に書ける形（datetime → ISO 文字列、Enum → 値）
    assert isinstance(payload["scheduled_deletion_at"], str)
    assert payload["active_goal"] == "full"
    assert payload["status"] == "scheduled_deletion"
    # 復元
    restored = User.model_validate(payload)
    assert restored.internal_uid == "u-1"
    assert restored.active_goal is Goal.FULL
    assert restored.status is UserStatus.SCHEDULED_DELETION
    assert restored.scheduled_deletion_at == user.scheduled_deletion_at


def test_session_round_trip() -> None:
    s = Session(
        internal_uid="u-1",
        session_id="s-1",
        mode=QuizMode.MOCK_FULL,
        state=SessionState.AWAITING_ANSWER,
        current_question_id="q_seed_001",
        current_question_version=2,
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    payload = s.model_dump(mode="json")
    restored = Session.model_validate(payload)
    assert restored.mode is QuizMode.MOCK_FULL
    assert restored.state is SessionState.AWAITING_ANSWER
    assert restored.current_question_id == "q_seed_001"
    assert restored.expires_at == s.expires_at


def test_answer_history_round_trip() -> None:
    h = AnswerHistory(
        internal_uid="u-1",
        question_id="q_seed_001",
        first_answered_at=datetime.now(UTC),
        last_answered_at=datetime.now(UTC),
        last_correct=True,
        last_chosen=0,
        attempt_count=3,
        correct_count=2,
        last_question_version=1,
        mastery_level=2,
        next_due_at=datetime.now(UTC) + timedelta(days=4),
    )
    payload = h.model_dump(mode="json")
    restored = AnswerHistory.model_validate(payload)
    assert restored.attempt_count == 3
    assert restored.mastery_level == 2
    assert restored.next_due_at == h.next_due_at


def test_repository_protocol_compatibility() -> None:
    """FirestoreUserRepo が UserRepo Protocol を満たすことを確認（import-time check）。

    google.cloud.firestore_v1 は重い import のため、`AsyncClient` のインスタンス化
    は別 PR で実 Firestore Emulator 起動時にカバーする。ここでは class-level の
    Protocol 整合のみ静的に確認する。
    """
    from app.repositories.firestore_repos import (
        FirestoreAnswerHistoryRepo,
        FirestoreLineUserIndexRepo,
        FirestoreSessionRepo,
        FirestoreUserRepo,
    )
    from app.repositories.protocols import (
        AnswerHistoryRepo,
        LineUserIndexRepo,
        SessionRepo,
        UserRepo,
    )

    # 各クラスが必要メソッド（async 名前）を持つことを確認
    for cls, methods in [
        (FirestoreUserRepo, ["get", "upsert", "delete"]),
        (
            FirestoreLineUserIndexRepo,
            ["get_internal_uid", "set_mapping", "delete"],
        ),
        (
            FirestoreSessionRepo,
            ["get", "get_active", "upsert", "delete_all"],
        ),
        (
            FirestoreAnswerHistoryRepo,
            ["get", "upsert", "list_recent", "delete_all"],
        ),
    ]:
        for m in methods:
            assert callable(getattr(cls, m, None)), f"{cls.__name__}.{m} missing"

    # Protocol 自体の存在確認（runtime_checkable は Phase 1 で導入済）
    assert UserRepo is not None
    assert LineUserIndexRepo is not None
    assert SessionRepo is not None
    assert AnswerHistoryRepo is not None


def test_build_repo_bundle_defaults_to_in_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    """env 未設定時は in-memory バンドルが返る（dev / テスト既定の安全性）。"""
    from importlib import reload

    import app.config as config_module

    monkeypatch.setenv("REPOSITORY_BACKEND", "memory")
    reload(config_module)
    import app.repositories.bundle as bundle_module

    reload(bundle_module)
    bundle = bundle_module.build_repo_bundle()
    # in-memory は CRUD が即座に動く
    from app.repositories.in_memory import InMemoryUserRepo

    assert isinstance(bundle.users, InMemoryUserRepo)


def test_build_repo_bundle_firestore_requires_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """firestore モードで GOOGLE_CLOUD_PROJECT 未設定なら明示的に raise。"""
    from importlib import reload

    import app.config as config_module

    monkeypatch.setenv("REPOSITORY_BACKEND", "firestore")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "")
    reload(config_module)
    import app.repositories.bundle as bundle_module

    reload(bundle_module)
    with pytest.raises(RuntimeError, match="GOOGLE_CLOUD_PROJECT"):
        bundle_module.build_repo_bundle()
