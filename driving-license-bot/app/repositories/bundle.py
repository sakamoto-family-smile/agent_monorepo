"""リポジトリバンドルとファクトリ（env で in-memory ↔ Firestore を切替）。

env `REPOSITORY_BACKEND`:
- `memory` (default): InMemoryRepoBundle
- `firestore`: FirestoreRepoBundle（GOOGLE_CLOUD_PROJECT 必須）

handler / service 層は Protocol しか見ないため、本ファクトリの戻り値が
入れ替わるだけで挙動が切り替わる。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import app.config  # NOTE: モジュール参照で取り、reload 後も最新 settings を参照する。
from app.repositories.in_memory import (
    InMemoryRepoBundle,
)
from app.repositories.protocols import (
    AnswerHistoryRepo,
    LineUserIndexRepo,
    SessionRepo,
    UserRepo,
)

logger = logging.getLogger(__name__)


@dataclass
class RepoBundleImpl:
    """Protocol 実装の値オブジェクト（in-memory / Firestore どちらでも同型）。"""

    users: UserRepo
    line_user_index: LineUserIndexRepo
    sessions: SessionRepo
    answer_histories: AnswerHistoryRepo


def build_repo_bundle() -> RepoBundleImpl:
    """env を見てバンドルを構築する。"""
    backend = app.config.settings.repository_backend.lower()
    if backend == "firestore":
        return _build_firestore_bundle()
    if backend != "memory":
        logger.warning(
            "REPOSITORY_BACKEND=%r is unknown, falling back to in-memory",
            backend,
        )
    return _build_in_memory_bundle()


def _build_in_memory_bundle() -> RepoBundleImpl:
    bundle = InMemoryRepoBundle()
    return RepoBundleImpl(
        users=bundle.users,
        line_user_index=bundle.line_user_index,
        sessions=bundle.sessions,
        answer_histories=bundle.answer_histories,
    )


def _build_firestore_bundle() -> RepoBundleImpl:
    """Firestore バンドルを構築する。

    Firestore 関連の import は遅延し、`google-cloud-firestore` が未インストール
    の環境でも in-memory モードでアプリ起動できるようにする。
    """
    if not app.config.settings.google_cloud_project:
        raise RuntimeError(
            "REPOSITORY_BACKEND=firestore requires GOOGLE_CLOUD_PROJECT env var"
        )
    try:
        from google.cloud.firestore_v1 import AsyncClient

        from app.repositories.firestore_repos import (
            FirestoreAnswerHistoryRepo,
            FirestoreLineUserIndexRepo,
            FirestoreSessionRepo,
            FirestoreUserRepo,
        )
    except ImportError as exc:  # pragma: no cover — google-cloud-firestore 未導入時
        raise RuntimeError(
            "google-cloud-firestore is required for REPOSITORY_BACKEND=firestore"
        ) from exc

    project = app.config.settings.google_cloud_project
    database = app.config.settings.firestore_database
    client = AsyncClient(project=project, database=database)
    logger.info(
        "firestore client initialized project=%s database=%s", project, database
    )
    return RepoBundleImpl(
        users=FirestoreUserRepo(client),
        line_user_index=FirestoreLineUserIndexRepo(client),
        sessions=FirestoreSessionRepo(client),
        answer_histories=FirestoreAnswerHistoryRepo(client),
    )


__all__ = ["RepoBundleImpl", "build_repo_bundle"]
