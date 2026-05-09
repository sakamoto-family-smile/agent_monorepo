"""embedding client のテスト。

Vertex 実装は実 API 呼出のため CI ではテストしない (本番疎通 smoke は別途)。
本テストは Protocol 契約と MockEmbeddingClient の決定性を検証する。
"""

from __future__ import annotations

from fujisawa_platform.knowledge_base.embedding import (
    EmbeddingClient,
    MockEmbeddingClient,
)


class TestProtocol:
    def test_mock_satisfies_protocol(self) -> None:
        """MockEmbeddingClient は EmbeddingClient Protocol を満たす。"""
        client: EmbeddingClient = MockEmbeddingClient()
        assert isinstance(client, EmbeddingClient)

    def test_non_implementor_does_not_satisfy_protocol(self) -> None:
        """関係ないオブジェクトは Protocol を満たさない (runtime check が効く)。"""

        class _Unrelated:
            pass

        assert not isinstance(_Unrelated(), EmbeddingClient)


class TestMockEmbedding:
    def test_default_dimension_is_768(self) -> None:
        """default は Vertex text-embedding-004 と揃えて 768 dim。"""
        client = MockEmbeddingClient()
        assert client.dimension == 768

    def test_custom_dimension(self) -> None:
        client = MockEmbeddingClient(dimension=128)
        assert client.dimension == 128

    def test_returns_vector_of_correct_length(self) -> None:
        client = MockEmbeddingClient(dimension=64)
        vec = client.embed("hello")
        assert len(vec) == 64
        assert all(isinstance(x, float) for x in vec)

    def test_deterministic_same_input_same_vector(self) -> None:
        """同じ入力 → 同じベクトル (dedup テストの前提)。"""
        client = MockEmbeddingClient()
        vec1 = client.embed("藤沢保育園")
        vec2 = client.embed("藤沢保育園")
        assert vec1 == vec2

    def test_different_input_different_vector(self) -> None:
        """異なる入力 → 異なるベクトル (衝突しない、SHA-256 ベースなので確率的に)。"""
        client = MockEmbeddingClient()
        vec1 = client.embed("藤沢保育園")
        vec2 = client.embed("辻堂保育園")
        assert vec1 != vec2

    def test_normalized_to_unit_length(self) -> None:
        """L2 正規化済み (cosine = 内積 で計算できる)。"""
        client = MockEmbeddingClient()
        vec = client.embed("hello")
        norm_sq = sum(x * x for x in vec)
        # 浮動小数点誤差を許容
        assert 0.99 < norm_sq < 1.01

    def test_records_calls(self) -> None:
        """テスト用に呼び出し履歴を記録。"""
        client = MockEmbeddingClient()
        client.embed("a")
        client.embed("b")
        assert client.calls == ["a", "b"]

    def test_embed_batch(self) -> None:
        """バッチ呼出 (Phase 2.5 で Vertex 側もバッチ化する想定)。"""
        client = MockEmbeddingClient()
        vecs = client.embed_batch(["a", "b", "c"])
        assert len(vecs) == 3
        assert all(len(v) == 768 for v in vecs)
