"""Embedding クライアント抽象。

Vertex AI `text-embedding-004`（既定 768 次元）をラップする。Question Bank の
類似度検索（pgvector）の特徴ベクトル生成に使う。

LLM クライアント同様、Protocol で抽象化してテストでは `MockEmbeddingClient`
を DI する。Mock は決定的（テキストのハッシュベースで同じ入力に同じベクトル）。
"""

from __future__ import annotations

import hashlib
import logging
import math
from typing import Protocol, runtime_checkable

import app.config
from app.agent.errors import LLMClientError

logger = logging.getLogger(__name__)


@runtime_checkable
class EmbeddingClient(Protocol):
    """単一テキスト → 単一 embedding（list[float]）の同期 API。

    Vertex AI の API 自体はバッチ呼び出し可能だが、Phase 2-D では 1 件ずつで十分。
    Phase 5+ で大量バッチ生成時にバッチ API へ拡張する。
    """

    @property
    def dimension(self) -> int: ...

    def embed(self, text: str) -> list[float]: ...


class MockEmbeddingClient:
    """テスト用の決定的 embedding クライアント。

    SHA256 ハッシュをシードにした擬似ベクトルを返す。同じ入力 → 同じベクトル
    なので、in-memory dedup テストで「同じ問題は同じベクトル」を仮定できる。
    """

    def __init__(self, *, dimension: int = 768) -> None:
        self._dimension = dimension
        self.calls: list[str] = []

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        # 32 バイトを `dimension` 個に拡張: digest を周期的に使い float に変換
        out = []
        for i in range(self._dimension):
            byte = digest[i % len(digest)]
            # -1.0〜1.0 にマップ
            out.append((byte / 127.5) - 1.0)
        # L2 正規化（cosine 類似度を内積で計算しやすくするため）
        norm = math.sqrt(sum(x * x for x in out)) or 1.0
        return [x / norm for x in out]


class VertexEmbeddingClient:
    """Vertex AI 経由の embedding クライアント。

    認証は Workload Identity に委ね、API キーは持たない。
    Phase 2-D では 1 件ずつ呼ぶ（バッチ最適化は Phase 5+）。
    """

    def __init__(
        self,
        *,
        project_id: str,
        region: str,
        model: str,
        dimension: int,
    ) -> None:
        self._project_id = project_id
        self._region = region
        self._model = model
        self._dimension = dimension
        try:
            import vertexai
            from vertexai.language_models import TextEmbeddingModel
        except ImportError as exc:  # pragma: no cover — google-cloud-aiplatform 未導入時
            raise LLMClientError(
                "google-cloud-aiplatform (vertexai) is required for VertexEmbeddingClient"
            ) from exc
        vertexai.init(project=project_id, location=region)
        self._model_obj = TextEmbeddingModel.from_pretrained(model)
        logger.info(
            "VertexEmbeddingClient initialized project=%s region=%s model=%s dim=%d",
            project_id,
            region,
            model,
            dimension,
        )

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, text: str) -> list[float]:
        try:
            embeddings = self._model_obj.get_embeddings([text])
        except Exception as exc:  # noqa: BLE001
            raise LLMClientError(f"Vertex embedding call failed: {exc}") from exc
        if not embeddings:
            raise LLMClientError("Vertex embedding returned no results")
        values = list(embeddings[0].values)
        if len(values) != self._dimension:
            logger.warning(
                "embedding dimension mismatch expected=%d actual=%d",
                self._dimension,
                len(values),
            )
        return values


def build_embedding_client() -> EmbeddingClient:
    """env から実 embedding クライアントを構築する。

    `EMBEDDING_MOCK=true` で MockEmbeddingClient（CI / 開発の安全弁）。
    `GOOGLE_CLOUD_PROJECT` 必須。
    """
    settings = app.config.settings
    if settings.embedding_mock:
        logger.warning("EMBEDDING_MOCK=true: returning MockEmbeddingClient")
        return MockEmbeddingClient(dimension=settings.embedding_dim)
    project = settings.google_cloud_project or settings.anthropic_vertex_project_id
    if not project:
        raise LLMClientError(
            "GOOGLE_CLOUD_PROJECT is required for VertexEmbeddingClient"
        )
    return VertexEmbeddingClient(
        project_id=project,
        region=settings.cloud_ml_region,
        model=settings.embedding_model,
        dimension=settings.embedding_dim,
    )


__all__ = [
    "EmbeddingClient",
    "MockEmbeddingClient",
    "VertexEmbeddingClient",
    "build_embedding_client",
]
