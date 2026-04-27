"""pytest 共通フィクスチャ。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.handlers.command_router import HandlerDeps
from app.repositories import InMemoryRepoBundle, load_question_pool
from app.repositories.question_pool import QuestionPool

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = REPO_ROOT / "app" / "data" / "seed_questions.json"


@pytest.fixture
def question_pool() -> QuestionPool:
    return load_question_pool(SEED_PATH)


@pytest.fixture
def repo_bundle() -> InMemoryRepoBundle:
    return InMemoryRepoBundle()


@pytest.fixture
def deps(question_pool: QuestionPool, repo_bundle: InMemoryRepoBundle) -> HandlerDeps:
    return HandlerDeps(
        users=repo_bundle.users,
        line_user_index=repo_bundle.line_user_index,
        sessions=repo_bundle.sessions,
        answer_histories=repo_bundle.answer_histories,
        pool=question_pool,
    )


@pytest.fixture(autouse=True)
def _reset_line_singletons() -> Iterator[None]:
    """各テスト後に line_client / route のシングルトンをリセット。"""
    yield
    from app.routes import line as line_route
    from app.services import line_client as line_client_module

    line_client_module.reset_line_bot_client()
    line_route.set_repo_bundle(None)
    line_route.set_question_pool(None)
