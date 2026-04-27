"""Fact Checker Agent — 引用条文の実在性と quoted_text の整合性を検証する。

設計（DESIGN.md §3.2）:
1. 引用条文の URL が grounding corpus に存在するかチェック
2. quoted_text が corpus snippet の text と十分類似しているか（>0.7）
3. NG の場合は理由を含めて reject

Phase 2-C は corpus.py の hardcode 辞書ベース。Phase 4 で law-mcp 経由の
e-Gov 法令検索 API + 教則 PDF 検索に差し替える際は、本ファイルの URL/text
ルックアップ部分を取り換えるだけで済む。

LLM は使わない（rule-based）。これにより:
- レイテンシゼロ
- 結果が決定的（再現性）
- LLM コストゼロ
- 「ハルシネーション条文」を確実に弾ける（最重要）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.agent.corpus import CorpusSnippet, all_categories, pick_snippets
from app.models import Question, Source

logger = logging.getLogger(__name__)


# 既定しきい値
DEFAULT_QUOTED_TEXT_SIMILARITY_THRESHOLD = 0.3
"""quoted_text と corpus snippet text の類似度下限。

判定式は `_similarity` 参照:
- quoted が corpus に substring で含まれる → 1.0（理想的な引用）
- それ以外は `SequenceMatcher.ratio` (autojunk=False)

日本語は char 単位で SequenceMatcher が走るため、一致率は英語より
低めに出る傾向がある。0.3 は『要点となる句がそれなりに重なっている』
レベル。Phase 5 で運用結果を見て調整する想定。
"""


@dataclass
class FactIssue:
    """Fact Checker が検出した 1 件の不整合。"""

    source_index: int
    code: str  # url_not_in_corpus | quoted_text_low_similarity | missing_quoted_text
    message: str


@dataclass
class FactCheckResult:
    """Fact Checker の判定結果。"""

    passed: bool
    score: float  # 0.0〜1.0
    issues: list[FactIssue]

    @property
    def issue_codes(self) -> list[str]:
        return [i.code for i in self.issues]


def _build_url_index() -> dict[str, list[CorpusSnippet]]:
    """全カテゴリの corpus を URL でインデックス化。

    同一 URL（例: 道路交通法 _LAW_BASE）に複数の snippet（横断歩道 / 一時停止 /
    シートベルト 等）が紐づくため、リストで保持して quoted_text とのマッチを
    全 snippet で評価する。
    """
    index: dict[str, list[CorpusSnippet]] = {}
    seen: set[tuple[str, str]] = set()  # (url, text) 重複を排除
    for cat in all_categories():
        for snip in pick_snippets(cat, limit=100):
            key = (snip.url, snip.text)
            if key in seen:
                continue
            seen.add(key)
            index.setdefault(snip.url, []).append(snip)
    return index


def _similarity(quoted: str, corpus: str) -> float:
    """quoted_text が corpus.text に対してどれだけ忠実か。

    優先順:
    1. quoted が corpus に substring で含まれる → 1.0（verbatim quote）
    2. それ以外は char 単位 `SequenceMatcher.ratio`（autojunk=False）

    日本語の長文同士は autojunk=True だと共通文字が捨てられて誤検出するため
    autojunk=False を指定する。
    """
    if not quoted or not corpus:
        return 0.0
    if quoted.strip() in corpus:
        return 1.0
    return SequenceMatcher(None, quoted, corpus, autojunk=False).ratio()


class FactChecker:
    """rule-based の Fact Checker。LLM は呼ばない。"""

    def __init__(
        self,
        *,
        quoted_text_threshold: float = DEFAULT_QUOTED_TEXT_SIMILARITY_THRESHOLD,
    ) -> None:
        self._url_index = _build_url_index()
        self._quoted_threshold = quoted_text_threshold

    def check(self, question: Question) -> FactCheckResult:
        """各 source を検証。1 件でも url_not_in_corpus があれば即 fail。"""
        issues: list[FactIssue] = []
        per_source_scores: list[float] = []

        for idx, src in enumerate(question.sources):
            score, src_issues = self._check_source(idx, src)
            issues.extend(src_issues)
            per_source_scores.append(score)

        # url_not_in_corpus（最重要違反）が 1 つでもあれば即 fail
        has_critical = any(i.code == "url_not_in_corpus" for i in issues)
        passed = not has_critical and bool(per_source_scores)
        avg_score = (
            sum(per_source_scores) / len(per_source_scores)
            if per_source_scores
            else 0.0
        )
        return FactCheckResult(passed=passed, score=avg_score, issues=issues)

    def _check_source(
        self, idx: int, src: Source
    ) -> tuple[float, list[FactIssue]]:
        issues: list[FactIssue] = []
        snippets = self._url_index.get(src.url)
        if not snippets:
            issues.append(
                FactIssue(
                    source_index=idx,
                    code="url_not_in_corpus",
                    message=(
                        f"source.url={src.url} is not in known corpus. "
                        "LLM may have fabricated the citation."
                    ),
                )
            )
            return 0.0, issues

        if not src.quoted_text:
            issues.append(
                FactIssue(
                    source_index=idx,
                    code="missing_quoted_text",
                    message="quoted_text is empty; cannot validate citation",
                )
            )
            return 0.5, issues

        # 同一 URL の全 snippet 中で最大の類似度を採用する。
        # 例: 道路交通法 URL には複数条文の snippet が紐づくため、quoted_text が
        # どれか 1 つに合致すれば良い。
        sim = max(_similarity(src.quoted_text, s.text) for s in snippets)
        if sim < self._quoted_threshold:
            issues.append(
                FactIssue(
                    source_index=idx,
                    code="quoted_text_low_similarity",
                    message=(
                        f"quoted_text similarity={sim:.3f} below threshold "
                        f"{self._quoted_threshold}"
                    ),
                )
            )
        return sim, issues


__all__ = ["FactCheckResult", "FactChecker", "FactIssue"]
