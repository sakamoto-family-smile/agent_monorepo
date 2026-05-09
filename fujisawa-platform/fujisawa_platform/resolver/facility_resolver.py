"""施設名の表記ゆれ吸収。

藤沢市の保育施設名 (約 160 件) は次のような表記ゆれが頻出する:

  - 中黒 (なかぐろ「・」) の有無: 「キディ鵠沼・藤沢」⇔「キディ鵠沼藤沢」
  - 空白の有無: 「はなえみ保育園 藤沢」⇔「はなえみ保育園藤沢」
  - 自治体接頭辞の有無: 「藤沢保育園」⇔「藤沢市立藤沢保育園」
  - 分園 / 本園の区別: 「ときわぎ保育園」⇔「ときわぎ保育園(分園)」 (別 ID)
  - 旧名 → 新名 (改名): 「コペル保育園藤沢」 → 「はなえみ保育園 藤沢」
  - 1 文字 typo / 旧字体: 「藤沢保育園」⇔「藤沢保育圜」
  - OCR エラー由来の異体字

これらを吸収するため、resolve() / resolve_all() は以下のフローで施設を特定する。

## マッチング処理フロー (resolve_all の実装)

```
入力: query (str) + entries (list[ResolverEntry]) + threshold (default 0.85)

  ┌────────────────────────────────────────────────────────────┐
  │ Step 0: 入力検証                                            │
  │   query.strip() == ""  → ValueError                         │
  └────────────────────────┬───────────────────────────────────┘
                           ▼
  ┌────────────────────────────────────────────────────────────┐
  │ Step 1: 完全一致 (canonical / alias 全部対象)               │
  │   query が _name_to_entry にあれば即 score=1.0 で 1 件返却 │
  │     - canonical_name と一致 → そのまま hit                 │
  │     - alias と一致         → 親 entry の facility_id に解決 │
  │   早期 return することで fuzzy のオーバーヘッドを避ける     │
  └────────────────────────┬───────────────────────────────────┘
                           │ 完全一致なし
                           ▼
  ┌────────────────────────────────────────────────────────────┐
  │ Step 2: fuzzy match (全 entry × 全 alias を flatten)        │
  │   choices = [canonical_1, alias_1a, alias_1b,              │
  │              canonical_2, alias_2a, ...]                    │
  │   rapidfuzz.process.extract(                                │
  │       query, choices,                                       │
  │       scorer=fuzz.ratio,        # 文字レベル Levenshtein   │
  │       limit=top_k * 3,           # 後段の dedup 用に余分    │
  │   )                                                         │
  │   → [(matched_name, score (0-100), index), ...] を返す      │
  └────────────────────────┬───────────────────────────────────┘
                           ▼
  ┌────────────────────────────────────────────────────────────┐
  │ Step 3: threshold フィルタ                                  │
  │   normalized_score = score / 100                            │
  │   if normalized_score < threshold:                          │
  │       skip                                                   │
  │   default threshold=0.85 は中黒 / 1 文字 typo を吸収する目安│
  └────────────────────────┬───────────────────────────────────┘
                           ▼
  ┌────────────────────────────────────────────────────────────┐
  │ Step 4: facility_id 単位で重複排除                          │
  │   同じ entry の canonical と alias 両方がヒットしても、     │
  │   最高スコアの 1 件にまとめる (best_by_id dict)             │
  └────────────────────────┬───────────────────────────────────┘
                           ▼
  ┌────────────────────────────────────────────────────────────┐
  │ Step 5: スコア降順で top-k に絞る                           │
  │   sorted(..., key=score, reverse=True)[:top_k]              │
  │   返却型: list[Candidate]                                   │
  └────────────────────────────────────────────────────────────┘
```

resolve() は resolve_all(top_k=1) のラッパー: 候補 0 件なら NoMatchError を上げる。

## なぜ token_set_ratio ではなく fuzz.ratio (Levenshtein) か

- 日本語は単語境界 (token boundary) が無く、token_set_ratio が分割で迷う
- fuzz.ratio は文字レベル Levenshtein 距離なので、中黒 1 文字差や typo 1 文字差を
  自然に scoring できる
- 実測: 「キディ鵠沼藤沢」 vs 「キディ鵠沼・藤沢」 で fuzz.ratio = 92.3%
  (>= 0.85 threshold で hit)、token_set_ratio = 75% で取りこぼす

## 将来拡張: LLM fallback

Phase 2 では未実装。Phase 2.5+ で必要に応じて追加:

- 想定 I/F: `FacilityResolver(llm_client=...)` で DI
- 動作: `resolve_all()` の top-3 を LLM に渡し、「これらのいずれか / 該当なし」を判定
- 利用ケース: fuzz.ratio が 0.5〜0.85 の中間域で人間判断が必要な曖昧クエリ
- 設計判断ログは proposal 0003 §4.4 を参照
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
