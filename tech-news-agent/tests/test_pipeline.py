"""Pipeline E2E テスト (LLM / LINE / arXiv スタブ、実 SQLite)。"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

import instrumentation.setup as obs_setup
import pytest
from conftest import load_fixture_bytes
from llm_client import MockLLMClient
from models import CuratedArticle
from services.source_config import SourcesConfig


class _LlmStub:
    """system prompt で系を判定し、scorer / summarizer / tagger の応答を切替。"""

    def __init__(self, score_map: dict[str, int] | None = None) -> None:
        # title 先頭一致 → score マップ。デフォルトは 8 (通過)
        self._score_map = score_map or {}

    async def complete(self, *, system: str, user: str, cache_system: bool = False) -> str:
        if "キュレーター" in system and "0〜10 点で" in system:
            # scorer: user prompt 内に id / title を発見して応答
            # 行分割から "id: <n>" と "title: <t>" を抽出
            current_id = None
            current_title = None
            result: list[dict] = []
            for line in user.splitlines():
                line = line.strip()
                if line.startswith("id:"):
                    if current_id is not None and current_title is not None:
                        result.append(self._score_for(current_id, current_title))
                    current_id = int(line.split(":", 1)[1])
                    current_title = None
                elif line.startswith("title:") and current_id is not None:
                    current_title = line.split(":", 1)[1].strip()
            if current_id is not None and current_title is not None:
                result.append(self._score_for(current_id, current_title))
            return json.dumps(result)

        if "エディタ" in system and "要約" in system:
            return json.dumps({"summary_ja": "テスト用日本語要約。"})

        if "分類器" in system and "タグ" in system:
            return json.dumps({"tags": ["bigquery", "iceberg"]})

        return "{}"

    def _score_for(self, idx: int, title: str) -> dict:
        score = 8
        for key, val in self._score_map.items():
            if key.lower() in title.lower():
                score = val
                break
        return {"id": idx, "score": score, "reason": f"test idx={idx}"}

    async def complete_messages(self, **kwargs):  # noqa: D401
        return "ok"


@dataclass
class StubLineClient:
    pushed: list[tuple[str, str, dict]]
    should_fail: bool = False

    async def push_flex(self, *, user_ids, alt_text, contents):
        if self.should_fail:
            return (0, len(user_ids))
        for uid in user_ids:
            self.pushed.append((uid, alt_text, contents))
        return (len(user_ids), 0)

    async def push_text(self, *, user_ids, text):
        return (len(user_ids), 0)

    async def close(self):
        pass


@pytest.fixture
def env(monkeypatch, tmp_path):
    # analytics / SQLite / LLM mock
    monkeypatch.setenv("ANALYTICS_ENABLED", "false")
    monkeypatch.setenv("LLM_MOCK_MODE", "true")
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "s")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "t")
    monkeypatch.setenv("LINE_USER_IDS", "Uaaa,Ubbb")
    monkeypatch.setenv("RELEVANCE_THRESHOLD", "5.0")
    monkeypatch.setenv("TOP_NEWS_N", "2")
    monkeypatch.setenv("TOP_ARXIV_N", "0")
    monkeypatch.setenv("TECH_NEWS_DB_PATH", str(tmp_path / "p.db"))
    monkeypatch.setenv("ANALYTICS_DATA_DIR", str(tmp_path / "analytics"))

    import config as config_mod
    importlib.reload(config_mod)
    importlib.reload(obs_setup)
    obs_setup.setup_observability()
    yield
    obs_setup.reset_for_tests()


@pytest.fixture
def stub_rss(monkeypatch):
    import collectors.rss as rss_mod

    async def fake_http(url: str) -> bytes:
        return load_fixture_bytes("sample_feed.xml")

    # 個別ソースの fetch を stub に差替
    async def fake_fetch_source(source, *, http_fetch=None):
        return await rss_mod.fetch_source(source, http_fetch=fake_http)

    monkeypatch.setattr(rss_mod, "_default_http_fetch", fake_http)


@pytest.fixture
def stub_arxiv(monkeypatch):
    import collectors.arxiv_source as arxiv_mod

    async def fake_fetch_all(sources):
        return []

    monkeypatch.setattr(arxiv_mod, "fetch_all", fake_fetch_all)


@pytest.fixture
def sources() -> SourcesConfig:
    from services.source_config import RssSourceConfig

    return SourcesConfig(
        domain="data_platform",
        rss=(RssSourceConfig(name="sample", url="https://x/feed", priority=3, weight=1.5),),
        arxiv=(),
    )


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_end_to_end_publishes_digest(
    env, stub_rss, stub_arxiv, sources, tmp_path
):
    from repositories.dedup_repo import DedupRepo
    from services.pipeline import run_pipeline

    line_stub = StubLineClient(pushed=[])
    dedup = DedupRepo(db_path=str(tmp_path / "pipe.db"))
    await dedup.initialize()

    result = await run_pipeline(
        llm=_LlmStub(),
        line=line_stub,
        dedup=dedup,
        sources=sources,
    )
    assert result.status == "sent"
    assert result.collected_count == 2
    assert result.new_count == 2
    assert result.news_count <= 2
    # 2 人への push
    assert len(line_stub.pushed) == result.line_success == 2
    # 配信済みとして SQLite に登録される
    assert await dedup.count_delivered() == result.news_count


@pytest.mark.asyncio
async def test_pipeline_skips_already_delivered_articles(
    env, stub_rss, stub_arxiv, sources, tmp_path
):
    from repositories.dedup_repo import DedupRepo
    from services.pipeline import run_pipeline

    line_stub = StubLineClient(pushed=[])
    dedup = DedupRepo(db_path=str(tmp_path / "pipe.db"))
    await dedup.initialize()

    # 1 回目
    r1 = await run_pipeline(llm=_LlmStub(), line=line_stub, dedup=dedup, sources=sources)
    assert r1.status == "sent"
    first_count = r1.news_count

    # 2 回目: 同じ RSS を返すが全て delivered 済みなので new=0
    line_stub.pushed.clear()
    r2 = await run_pipeline(llm=_LlmStub(), line=line_stub, dedup=dedup, sources=sources)
    assert r2.new_count == 0
    assert r2.status == "empty"
    assert line_stub.pushed == []
    # 配信済みテーブルは r1 の分だけ
    assert await dedup.count_delivered() == first_count


@pytest.mark.asyncio
async def test_pipeline_below_threshold_produces_empty_digest(
    env, stub_rss, stub_arxiv, sources, tmp_path
):
    """全 article が閾値未達なら status='empty' + LINE に送らない。"""
    from repositories.dedup_repo import DedupRepo
    from services.pipeline import run_pipeline

    line_stub = StubLineClient(pushed=[])
    dedup = DedupRepo(db_path=str(tmp_path / "pipe.db"))
    await dedup.initialize()

    # スコア 1 点固定 (threshold 5.0 未達)
    low_llm = _LlmStub(score_map={"BigQuery": 1, "dbt": 1})
    result = await run_pipeline(llm=low_llm, line=line_stub, dedup=dedup, sources=sources)
    assert result.status == "empty"
    assert line_stub.pushed == []


@pytest.mark.asyncio
async def test_pipeline_line_failure_marks_failed(
    env, stub_rss, stub_arxiv, sources, tmp_path
):
    from repositories.dedup_repo import DedupRepo
    from services.pipeline import run_pipeline

    failing = StubLineClient(pushed=[], should_fail=True)
    dedup = DedupRepo(db_path=str(tmp_path / "pipe.db"))
    await dedup.initialize()

    result = await run_pipeline(llm=_LlmStub(), line=failing, dedup=dedup, sources=sources)
    assert result.status == "failed"
    # 失敗時は配信済み登録しない (再配信の余地を残す)
    assert await dedup.count_delivered() == 0


@pytest.mark.asyncio
async def test_mock_llm_client_is_acceptable_though_scoring_degrades(
    env, stub_rss, stub_arxiv, sources, tmp_path
):
    """MockLLMClient は JSON 形式の応答を返さないので scorer は全件 0 点になる。
    → status='empty' で正しくハンドリングされる。"""
    from repositories.dedup_repo import DedupRepo
    from services.pipeline import run_pipeline

    line_stub = StubLineClient(pushed=[])
    dedup = DedupRepo(db_path=str(tmp_path / "pipe.db"))
    await dedup.initialize()

    result = await run_pipeline(
        llm=MockLLMClient(), line=line_stub, dedup=dedup, sources=sources
    )
    assert result.status == "empty"
    assert line_stub.pushed == []


# ---------------------------------------------------------------------------
# util: Curator の単発関数も念のためモックで動作確認
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scorer_batch_handles_parse_failure_gracefully():
    """LLM が壊れた応答を返してもバッチは 0 点でフォールバック。"""
    from curator.scorer import score_articles
    from models import RawArticle

    class _BrokenLlm:
        async def complete(self, *, system, user, cache_system=False):
            return "not valid json"

        async def complete_messages(self, **kwargs):
            return ""

    article = RawArticle(
        article_id="a",
        source_type="rss",
        source_name="s",
        url="https://x/a",
        url_normalized="https://x/a",
        title="T",
        content="",
        content_preview="",
        fetched_at=datetime.now(UTC),
    )
    result = await score_articles(_BrokenLlm(), [article])
    assert result["a"].score == 0.0


def _assert_curated_has_final_score(c: CuratedArticle, expected: float) -> None:
    assert c.final_score == expected
