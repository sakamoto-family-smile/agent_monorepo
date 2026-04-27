"""Fact Checker のユニットテスト（rule-based のため LLM 不要）。"""

from __future__ import annotations

from app.agent.fact_checker import (
    DEFAULT_QUOTED_TEXT_SIMILARITY_THRESHOLD,
    FactChecker,
)
from app.models import Question, QuestionFormat, Source

# corpus.py に登録済みの実 URL
KNOWN_LAW_URL = "https://laws.e-gov.go.jp/document?lawid=335AC0000000105"
KNOWN_ENF_URL = "https://laws.e-gov.go.jp/document?lawid=335CO0000000270"
UNKNOWN_URL = "https://example.com/fake-law"


def _make_question(*, sources: list[Source]) -> Question:
    return Question(
        id="q_check_001",
        body="テスト用問題",
        format=QuestionFormat.TRUE_FALSE,
        choices=[
            {"index": 0, "text": "正しい"},
            {"index": 1, "text": "誤り"},
        ],
        correct=0,
        explanation="テスト用解説",
        applicable_goals=["provisional", "full"],
        sources=sources,
    )


def test_url_in_corpus_passes() -> None:
    """corpus に存在する URL を引用していれば passed=True。"""
    src = Source(
        type="law",
        title="道路交通法 第 38 条",
        url=KNOWN_LAW_URL,
        quoted_text="車両等が横断歩道に接近する場合に横断しようとする歩行者があるときは、その手前で一時停止し、",
    )
    q = _make_question(sources=[src])
    result = FactChecker().check(q)
    assert result.passed is True
    assert result.score > DEFAULT_QUOTED_TEXT_SIMILARITY_THRESHOLD


def test_unknown_url_fails_with_critical_issue() -> None:
    """corpus 外の URL は『ハルシネーション条文』として即 fail。"""
    src = Source(
        type="law",
        title="架空法令",
        url=UNKNOWN_URL,
        quoted_text="この条文は実在しない",
    )
    q = _make_question(sources=[src])
    result = FactChecker().check(q)
    assert result.passed is False
    assert result.score == 0.0
    assert "url_not_in_corpus" in result.issue_codes


def test_low_similarity_quoted_text_flagged_but_not_critical() -> None:
    """URL は正しいが quoted_text が無関係 → issue は出るが critical fail ではない。"""
    src = Source(
        type="law",
        title="道路交通法 第 38 条",
        url=KNOWN_LAW_URL,
        quoted_text="まったく無関係な文章。これは引用ではありません。",
    )
    q = _make_question(sources=[src])
    result = FactChecker(quoted_text_threshold=0.5).check(q)
    # critical (url_not_in_corpus) は無いので passed=True、ただし issue は記録される
    assert result.passed is True
    assert "quoted_text_low_similarity" in result.issue_codes


def test_missing_quoted_text_flagged() -> None:
    src = Source(
        type="law",
        title="道路交通法 第 38 条",
        url=KNOWN_LAW_URL,
        quoted_text=None,
    )
    q = _make_question(sources=[src])
    result = FactChecker().check(q)
    assert result.passed is True  # critical ではない
    assert "missing_quoted_text" in result.issue_codes


def test_multiple_sources_fail_if_any_url_unknown() -> None:
    """複数 sources のうち 1 つでも URL 未知なら fail。"""
    good = Source(
        type="law",
        title="道路交通法施行令",
        url=KNOWN_ENF_URL,
        quoted_text="一般道路における自動車の法定最高速度は時速 60 キロメートル。",
    )
    bad = Source(
        type="law",
        title="架空法令",
        url=UNKNOWN_URL,
        quoted_text="架空",
    )
    q = _make_question(sources=[good, bad])
    result = FactChecker().check(q)
    assert result.passed is False
    assert "url_not_in_corpus" in result.issue_codes


def test_threshold_can_be_tightened() -> None:
    """非 substring の弱い引用は、threshold を厳しくすると検出される。"""
    src = Source(
        type="law",
        title="道路交通法 第 38 条",
        url=KNOWN_LAW_URL,
        # corpus にこの並びは存在しない（substring にならない）。char 重複は少しある。
        quoted_text="横断時の歩行者を妨害しない",
    )
    q = _make_question(sources=[src])
    relaxed = FactChecker(quoted_text_threshold=0.05).check(q)
    strict = FactChecker(quoted_text_threshold=0.95).check(q)
    assert "quoted_text_low_similarity" not in relaxed.issue_codes
    assert "quoted_text_low_similarity" in strict.issue_codes


def test_substring_quote_gets_perfect_score() -> None:
    """corpus.text の一部分を verbatim 引用していれば similarity=1.0。"""
    src = Source(
        type="law",
        title="道路交通法 第 38 条",
        url=KNOWN_LAW_URL,
        quoted_text="横断歩道",  # corpus の中に substring で存在する
    )
    q = _make_question(sources=[src])
    result = FactChecker(quoted_text_threshold=0.5).check(q)
    assert result.passed is True
    assert result.score == 1.0
    assert "quoted_text_low_similarity" not in result.issue_codes
