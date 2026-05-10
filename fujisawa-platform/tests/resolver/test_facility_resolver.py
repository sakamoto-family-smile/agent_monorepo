"""FacilityResolver のテスト。

藤沢市の保育施設名は表記ゆれが多発するため、fuzzy match + alias dict で
正規化する (proposal 0003 §4.4 / 0005 §38.5)。

例:
  - 「藤沢保育園」「藤沢市立藤沢保育園」 → 同一施設
  - 「キディ鵠沼・藤沢」「キディ鵠沼藤沢」 (中黒の有無) → 同一施設
  - 「ときわぎ保育園」「ときわぎ保育園(分園)」 → 別扱い (分園は独立)
  - 名称変更 (「コペル保育園藤沢」→「はなえみ保育園 藤沢」) → alias dict で吸収
"""

from __future__ import annotations

import pytest

from fujisawa_platform.resolver import (
    Candidate,
    FacilityResolver,
    NoMatchError,
    ResolverEntry,
)


@pytest.fixture
def entries() -> list[ResolverEntry]:
    """テスト用の正規化済 entry リスト。"""
    return [
        ResolverEntry(
            facility_id="fuji-001",
            canonical_name="藤沢保育園",
            aliases=["藤沢市立藤沢保育園"],
        ),
        ResolverEntry(
            facility_id="kidy-001",
            canonical_name="キディ鵠沼・藤沢",
            aliases=["キディ鵠沼藤沢"],
        ),
        ResolverEntry(
            facility_id="kidy-002",
            canonical_name="キディ鵠沼・藤沢(分園)",
            aliases=["キディ鵠沼藤沢分園"],
        ),
        ResolverEntry(
            facility_id="tokiwagi-001",
            canonical_name="ときわぎ保育園",
            aliases=[],
        ),
        ResolverEntry(
            facility_id="tokiwagi-002",
            canonical_name="ときわぎ保育園(分園)",
            aliases=["ときわぎ保育園分園"],
        ),
        ResolverEntry(
            facility_id="hanaemi-001",
            canonical_name="はなえみ保育園 藤沢",
            aliases=["コペル保育園藤沢"],  # 名称変更前
        ),
    ]


class TestExactMatch:
    def test_canonical_name_exact_match(self, entries: list[ResolverEntry]) -> None:
        """canonical_name と完全一致なら 1.0 で hit。"""
        resolver = FacilityResolver(entries)
        result = resolver.resolve("藤沢保育園")
        assert result.facility_id == "fuji-001"
        assert result.score == 1.0

    def test_alias_exact_match(self, entries: list[ResolverEntry]) -> None:
        """alias と完全一致でも 1.0。"""
        resolver = FacilityResolver(entries)
        result = resolver.resolve("藤沢市立藤沢保育園")
        assert result.facility_id == "fuji-001"
        assert result.score == 1.0

    def test_renamed_facility_via_alias(self, entries: list[ResolverEntry]) -> None:
        """旧名称 (コペル) も alias に入っていれば現在の施設に解決される。"""
        resolver = FacilityResolver(entries)
        result = resolver.resolve("コペル保育園藤沢")
        assert result.facility_id == "hanaemi-001"


class TestFuzzyMatch:
    def test_nakaguro_variation(self, entries: list[ResolverEntry]) -> None:
        """中黒「・」の有無を吸収。"""
        resolver = FacilityResolver(entries, threshold=0.8)
        result = resolver.resolve("キディ鵠沼藤沢")
        assert result.facility_id == "kidy-001"
        # alias なので 1.0
        assert result.score == 1.0

    def test_whitespace_variation(self, entries: list[ResolverEntry]) -> None:
        """空白の有無を吸収 (実際の表記ゆれパターン)。"""
        resolver = FacilityResolver(entries, threshold=0.8)
        # 「はなえみ保育園 藤沢」 (canonical) vs 空白なし
        result = resolver.resolve("はなえみ保育園藤沢")
        assert result.facility_id == "hanaemi-001"
        assert result.score >= 0.8

    def test_single_char_typo(self, entries: list[ResolverEntry]) -> None:
        """1 文字の typo (旧字体 / OCR エラー等) を許容。"""
        resolver = FacilityResolver(entries, threshold=0.7)
        # 1 文字置換 (園 → 圜)
        result = resolver.resolve("藤沢保育圜")
        assert result.facility_id == "fuji-001"
        assert result.score >= 0.7

    def test_distinguishes_main_and_branch(self, entries: list[ResolverEntry]) -> None:
        """分園は本園と別 facility_id に解決される (canonical 名で区別)。"""
        resolver = FacilityResolver(entries, threshold=0.8)
        main = resolver.resolve("ときわぎ保育園")
        branch = resolver.resolve("ときわぎ保育園(分園)")
        assert main.facility_id == "tokiwagi-001"
        assert branch.facility_id == "tokiwagi-002"
        assert main.facility_id != branch.facility_id


class TestNoMatch:
    def test_unknown_facility_raises(self, entries: list[ResolverEntry]) -> None:
        """類似度が threshold 未満なら NoMatchError。"""
        resolver = FacilityResolver(entries, threshold=0.9)
        with pytest.raises(NoMatchError):
            resolver.resolve("全然違う施設名")

    def test_empty_query_raises(self, entries: list[ResolverEntry]) -> None:
        resolver = FacilityResolver(entries)
        with pytest.raises(ValueError, match="empty"):
            resolver.resolve("")


class TestResolveAll:
    def test_returns_top_k_candidates(self, entries: list[ResolverEntry]) -> None:
        """`resolve_all()` は score 降順で top-k を返す (LLM fallback / debug 用)。"""
        resolver = FacilityResolver(entries, threshold=0.5)
        candidates = resolver.resolve_all("ときわぎ保育園", top_k=2)
        assert len(candidates) == 2
        assert all(isinstance(c, Candidate) for c in candidates)
        assert candidates[0].score >= candidates[1].score

    def test_filters_below_threshold(self, entries: list[ResolverEntry]) -> None:
        """threshold 未満は除外される。"""
        resolver = FacilityResolver(entries, threshold=0.99)
        candidates = resolver.resolve_all("typo すぎる名前", top_k=5)
        assert candidates == []


class TestResolverEntry:
    def test_immutable(self) -> None:
        """ResolverEntry は frozen。"""
        from pydantic import ValidationError

        entry = ResolverEntry(facility_id="x", canonical_name="A", aliases=[])
        with pytest.raises(ValidationError):
            entry.facility_id = "y"  # type: ignore[misc]

    def test_facility_id_required(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ResolverEntry(facility_id="", canonical_name="A", aliases=[])
