"""hash_diff のテスト。"""

from __future__ import annotations

from fujisawa_platform.pdf_pipeline.hash_diff import (
    compute_hash,
    has_changed,
)


class TestComputeHash:
    def test_returns_sha256_hex(self) -> None:
        h = compute_hash(b"hello")
        assert isinstance(h, str)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_deterministic(self) -> None:
        assert compute_hash(b"hello") == compute_hash(b"hello")

    def test_different_input_different_hash(self) -> None:
        assert compute_hash(b"hello") != compute_hash(b"world")

    def test_known_value(self) -> None:
        # SHA-256 of "" (empty bytes)
        assert compute_hash(b"") == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )


class TestHasChanged:
    def test_same_hash_unchanged(self) -> None:
        h = compute_hash(b"x")
        assert has_changed(h, h) is False

    def test_different_hash_changed(self) -> None:
        h1 = compute_hash(b"x")
        h2 = compute_hash(b"y")
        assert has_changed(h1, h2) is True

    def test_no_previous_hash_means_changed(self) -> None:
        """初回取得 (previous=None) は常に変更扱い → 全件 ETL 実行。"""
        assert has_changed(None, compute_hash(b"x")) is True

    def test_case_insensitive(self) -> None:
        """大文字小文字混在でも比較できる (堅牢性のため)。"""
        h = compute_hash(b"x")
        assert has_changed(h.upper(), h.lower()) is False
