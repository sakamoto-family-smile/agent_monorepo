"""施設名の表記ゆれ吸収。

3 段階で解決:
  1. canonical_name / alias の **完全一致** (score = 1.0)
  2. rapidfuzz の **fuzzy match** (score >= threshold)
  3. (将来) LLM fallback (Phase 2.5+ で proposal 0003 §4.4 に従い追加検討)

LLM fallback は Phase 2 では未実装。実装する場合は本クラスに `llm_client` を
DI して `resolve_all` で top-3 候補を渡し、LLM が「これらのいずれか」または
「該当なし」を返す形を想定する。
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, field_validator
from rapidfuzz import fuzz, process


class NoMatchError(LookupError):
    """類似度が threshold 未満で、該当施設が見つからない。"""


class ResolverEntry(BaseModel):
    """正規化済の 1 施設エントリ。"""

    model_config = ConfigDict(frozen=True)

    facility_id: str = Field(min_length=1, description="DB 上の主キー")
    canonical_name: str = Field(min_length=1, description="正規名 (HTML 一覧で表示される名前)")
    aliases: list[str] = Field(
        default_factory=list,
        description="表記ゆれ・旧名称等の別名。canonical_name と同等扱い。",
    )

    @field_validator("aliases")
    @classmethod
    def _strip_aliases(cls, v: list[str]) -> list[str]:
        return [a.strip() for a in v if a.strip()]

    def all_names(self) -> list[str]:
        """canonical + aliases を 1 リストで返す。"""
        return [self.canonical_name, *self.aliases]


@dataclass(frozen=True)
class Candidate:
    """解決候補 (score 付き)。"""

    facility_id: str
    canonical_name: str
    matched_name: str  # 一致した name (canonical or alias)
    score: float  # 0.0〜1.0


class FacilityResolver:
    """fuzzy match + alias dict による施設名正規化。

    Args:
        entries: 全施設の正規化エントリ。
        threshold: fuzzy match で許容する最低スコア (0.0〜1.0)。
            default 0.85 は「中黒の有無 / 軽微な typo」を吸収できる目安。
    """

    def __init__(self, entries: list[ResolverEntry], threshold: float = 0.85) -> None:
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(f"threshold must be in [0, 1], got {threshold}")
        self._entries = list(entries)
        self._threshold = threshold

        # 検索用 index: name → (entry, name 種別)
        self._name_to_entry: dict[str, ResolverEntry] = {}
        for entry in self._entries:
            for name in entry.all_names():
                # 完全一致時は最初に追加された entry を優先
                self._name_to_entry.setdefault(name, entry)

    def resolve(self, query: str) -> Candidate:
        """1 つの最適候補を返す。score >= threshold が必須。"""
        candidates = self.resolve_all(query, top_k=1)
        if not candidates:
            raise NoMatchError(f"no facility matches query: {query!r}")
        return candidates[0]

    def resolve_all(self, query: str, top_k: int = 5) -> list[Candidate]:
        """score 降順で top-k 候補を返す。threshold 未満は除外。

        score = 1.0 は完全一致、それ未満は rapidfuzz.fuzz.ratio (Levenshtein 類似度)。
        日本語は token_set_ratio が分割しにくいため文字レベルの ratio を採用。
        """
        if not query.strip():
            raise ValueError("query is empty")

        # 全 entry の全 name を flatten して rapidfuzz の process.extract に渡す
        choices: list[str] = []
        choice_to_entry: dict[int, ResolverEntry] = {}
        for entry in self._entries:
            for name in entry.all_names():
                choice_to_entry[len(choices)] = entry
                choices.append(name)

        # fuzz.ratio: 文字レベル Levenshtein。日本語の typo / 中黒の有無に強い。
        # 完全一致は score=100 で返るため、別経路は不要。
        results = process.extract(
            query,
            choices,
            scorer=fuzz.ratio,
            limit=top_k * 3,  # 同 entry の重複を弾くため余分に取る
        )

        # 重複排除 (同 facility_id は最高 score のみ残す)
        best_by_id: dict[str, Candidate] = {}
        for matched_name, score, idx in results:
            normalized_score = score / 100.0
            if normalized_score < self._threshold:
                continue
            entry = choice_to_entry[idx]
            existing = best_by_id.get(entry.facility_id)
            if existing is None or existing.score < normalized_score:
                best_by_id[entry.facility_id] = Candidate(
                    facility_id=entry.facility_id,
                    canonical_name=entry.canonical_name,
                    matched_name=matched_name,
                    score=normalized_score,
                )

        sorted_candidates = sorted(
            best_by_id.values(), key=lambda c: c.score, reverse=True
        )
        return sorted_candidates[:top_k]
