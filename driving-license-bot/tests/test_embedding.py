"""embedding service のテスト（Vertex 不使用、Mock のみ）。"""

from __future__ import annotations

import math

import pytest

from app.agent.embedding import MockEmbeddingClient


def test_mock_embedding_returns_correct_dimension() -> None:
    client = MockEmbeddingClient(dimension=768)
    vec = client.embed("テスト")
    assert client.dimension == 768
    assert len(vec) == 768


def test_mock_embedding_is_deterministic() -> None:
    """同じテキスト → 同じベクトル（dedup テストの前提）。"""
    client = MockEmbeddingClient(dimension=768)
    a = client.embed("一時停止の標識のある場所では停止しなければならない")
    b = client.embed("一時停止の標識のある場所では停止しなければならない")
    assert a == b


def test_mock_embedding_l2_normalized() -> None:
    """L2 ノルムが 1.0（cosine 類似度 = 内積で計算可能になる）。"""
    client = MockEmbeddingClient(dimension=768)
    vec = client.embed("テスト")
    norm = math.sqrt(sum(x * x for x in vec))
    assert abs(norm - 1.0) < 1e-6


def test_mock_embedding_calls_logged() -> None:
    client = MockEmbeddingClient()
    client.embed("a")
    client.embed("b")
    assert client.calls == ["a", "b"]


def test_different_dim_works() -> None:
    client = MockEmbeddingClient(dimension=128)
    vec = client.embed("テスト")
    assert len(vec) == 128


def test_build_embedding_client_with_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """EMBEDDING_MOCK=true → MockEmbeddingClient。"""
    from importlib import reload

    import app.config as config_module

    monkeypatch.setenv("EMBEDDING_MOCK", "true")
    reload(config_module)
    from app.agent.embedding import MockEmbeddingClient as _Mock
    from app.agent.embedding import build_embedding_client

    client = build_embedding_client()
    assert isinstance(client, _Mock)


def test_build_embedding_client_requires_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from importlib import reload

    import app.config as config_module

    monkeypatch.setenv("EMBEDDING_MOCK", "false")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "")
    monkeypatch.setenv("ANTHROPIC_VERTEX_PROJECT_ID", "")
    reload(config_module)
    from app.agent.embedding import build_embedding_client
    from app.agent.errors import LLMClientError

    with pytest.raises(LLMClientError, match="GOOGLE_CLOUD_PROJECT"):
        build_embedding_client()
