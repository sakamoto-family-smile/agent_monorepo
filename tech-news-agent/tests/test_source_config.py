"""sources.yaml ローダテスト。"""

from __future__ import annotations

from pathlib import Path

from services.source_config import load_sources

FIXTURES = Path(__file__).parent / "fixtures"


def test_loads_rss_and_arxiv_separately():
    cfg = load_sources(FIXTURES / "sample_sources.yaml")
    assert cfg.domain == "data_platform"
    assert len(cfg.rss) == 2
    assert len(cfg.arxiv) == 1
    assert {r.name for r in cfg.rss} == {"test_rss_a", "test_rss_b"}
    assert cfg.arxiv[0].categories == ("cs.DB", "cs.DC")


def test_priority_to_weight_mapping():
    cfg = load_sources(FIXTURES / "sample_sources.yaml")
    weights = {r.name: r.weight for r in cfg.rss}
    assert weights["test_rss_a"] == 1.5   # priority 3 → 1.5
    assert weights["test_rss_b"] == 1.0   # priority 2 → 1.0


def test_unknown_type_is_skipped():
    """priority 1 + unknown_type のエントリはスキップされ、rss 2 件 + arxiv 1 件だけ残る。"""
    cfg = load_sources(FIXTURES / "sample_sources.yaml")
    total = len(cfg.rss) + len(cfg.arxiv)
    assert total == 3


def test_real_sources_yaml_loads():
    """同梱の本番 sources.yaml がパースできる。"""
    cfg = load_sources(Path(__file__).parent.parent / "config" / "sources.yaml")
    assert cfg.domain == "data_platform"
    assert len(cfg.rss) >= 1
    assert len(cfg.arxiv) >= 1
