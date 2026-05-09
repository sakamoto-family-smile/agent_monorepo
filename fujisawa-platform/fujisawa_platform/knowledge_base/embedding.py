"""Embedding クライアント抽象。

driving-license-bot/app/agent/embedding.py のパターン (Protocol + Mock + Vertex)
を踏襲。本基盤の `pgvector_store` は Embedding を DI で受け取り、テストは
`MockEmbeddingClient` で deterministic にする。

Vertex AI `text-embedding-004` (768 dim) を本番 default とする。
"""

from __future__ import annotations

import hashlib
import math
from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingClient(Protocol):
    """テキスト → 単一 embedding (list[float]) の同期 API。"""

    @property
    def dimension(self) -> int: ...

    def embed(self, text: str) -> list[float]: ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


class MockEmbeddingClient:
    """テスト用の決定的 embedding クライアント。

    SHA-256 ハッシュをシードにした擬似ベクトルを返す。同じ入力 → 同じベクトル
    なので、dedup / cache テストに使える。

    L2 正規化済みなので、cosine 類似度を内積で計算できる。
    """

    def __init__(self, *, dimension: int = 768) -> None:
        if dimension < 1:
            raise ValueError(f"dimension must be >= 1, got {dimension}")
        self._dimension = dimension
        self.calls: list[str] = []

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        # 32 バイトを `dimension` 個に拡張: digest を周期的に使い float に変換
        out: list[float] = []
        for i in range(self._dimension):
            byte = digest[i % len(digest)]
            # -1.0〜1.0 にマップ
            out.append((byte / 127.5) - 1.0)
        # L2 正規化
        norm = math.sqrt(sum(x * x for x in out)) or 1.0
        return [x / norm for x in out]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


class VertexEmbeddingClient:
    """Vertex AI 経由の embedding クライアント。

    認証は Workload Identity に委ね、API キーは持たない。
    本クラスは optional dep `[vertex]` extra (`google-cloud-aiplatform`) が
    必要。利用側で `pip install fujisawa-platform[vertex]` する想定。

    `text-embedding-004` は 768 dim を返す。
    """

    def __init__(
        self,
        *,
        project_id: str,
        region: str = "asia-northeast1",
        model: str = "text-embedding-004",
        dimension: int = 768,
    ) -> None:
        self._project_id = project_id
        self._region = region
        self._model = model
        self._dimension = dimension
        self._model_instance = None  # lazy init

    def _ensure_model(self) -> object:
        """Vertex SDK は初回呼出時のみ import + initialize (重い)。"""
        if self._model_instance is None:
            try:
                import vertexai
                from vertexai.language_models import TextEmbeddingModel
            except ImportError as err:
                raise ImportError(
                    "VertexEmbeddingClient requires `google-cloud-aiplatform`. "
                    "Install with: `uv sync --extra vertex`"
                ) from err
            vertexai.init(project=self._project_id, location=self._region)
            self._model_instance = TextEmbeddingModel.from_pretrained(self._model)
        return self._model_instance

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        model = self._ensure_model()
        # type: ignore[attr-defined]
        responses = model.get_embeddings(texts)  # type: ignore[attr-defined]
        return [list(r.values) for r in responses]
