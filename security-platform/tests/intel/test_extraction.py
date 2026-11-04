"""L4: 記事の抽出の受け渡し (依頼 → extractor の結果の取り込み → grounding) のテスト。"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlalchemy import text

from src.common.db import make_engine
from src.common.migrate import upgrade_all
from src.common.paths import DataPaths
from src.common.timeutil import to_iso, utc_now
from src.intel import extraction
from src.intel.pipeline import IntelPipeline
from src.llm import exchange
from src.llm.providers import ExtractionFailed, FakeExtractor
from src.llm.worker import LlmDirs, Window, run_batch
from src.notify.health import extractor_checks

NOW = "2026-11-01T12:00:00.000000Z"
MALWARE = "The npm package left-padx version 1.0.3 contains malware that steals tokens."
CLAIM = {"ecosystem": "npm", "package": "left-padx", "versions": ["1.0.3", "9.9.9"], "kind": "malicious",
         "identifiers": [], "quote": "contains malware that steals tokens"}


@pytest.fixture
def env(tmp_path):
    paths = DataPaths(tmp_path / "data")
    upgrade_all(paths)
    p = IntelPipeline(
        make_engine(paths.sqlite_path("intel")), paths, None, lambda _: b"",  # type: ignore[arg-type]
        kev_url="", epss_url="", epss_delta=0.1, incremental_max_per_ecosystem=1, full_snapshots_kept=1,
    )
    llm = paths.llm_dir
    return p, LlmDirs(llm / "in", llm / "out", llm / "state")


def add_report(p: IntelPipeline, n: int, summary: str, *, initial: bool = False, trust: str = "research",
               h: str = "a") -> str:
    rid = f"rep_{n:024x}"
    with p.engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO reports (report_id, feed_id, guid, url, title, summary, trust, lang, initial, content_hash,
              raw_ref, first_seen_at, updated_at)
            VALUES (:r, 'feed-a', :r, 'https://ex.test/a', 'Security news', :s, :t, 'en', :i, :h, 'raw/x', :now, :now)
            ON CONFLICT(report_id) DO UPDATE SET summary = excluded.summary, content_hash = excluded.content_hash
        """), {"r": rid, "s": summary, "t": trust, "i": initial, "h": h * 64, "now": f"2026-11-01T00:00:{n:02d}Z"})
    return rid


def rows(p: IntelPipeline, sql: str) -> list[tuple]:
    with p.engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql)).all()]


def extract(dirs: LlmDirs, respond) -> None:
    run_batch(FakeExtractor(respond), dirs, Window(daily_limit=100), utc_now())


def test_queue_prefilters_and_skips_initial(env):
    p, dirs = env
    hit = add_report(p, 1, MALWARE)
    add_report(p, 2, "We shipped a faster dashboard.")  # 語がない
    add_report(p, 3, MALWARE, initial=True)  # 初回の取得で既にあった
    add_report(p, 4, MALWARE, trust="news")  # news はまだ対象外
    add_report(p, 5, "JPCERT: 脆弱性に関する注意喚起")
    r = p.run_extract()
    assert (r.queued, r.skipped) == (2, 1)
    assert rows(p, "SELECT report_id, status, reason FROM report_extractions ORDER BY report_id") == [
        (hit, "queued", None), (f"rep_{2:024x}", "skipped", "prefilter"), (f"rep_{5:024x}", "queued", None)]
    job = exchange.read_job(dirs.in_dir, exchange.list_ids(dirs.in_dir)[0])
    assert job.report_id == hit and job.text == MALWARE and job.title == "Security news"

    again = p.run_extract()  # 依頼済み・対象外は数え直さない
    assert (again.queued, again.skipped) == (0, 0) and len(exchange.list_ids(dirs.in_dir)) == 2


def test_ingest_grounds_claims(env):
    p, dirs = env
    rid = add_report(p, 1, MALWARE)
    p.run_extract()
    extract(dirs, lambda _i: {"about_specific_packages": True, "claims": [
        CLAIM, {**CLAIM, "package": "made-up-pkg", "quote": "a sentence that is not there"}]})
    r = p.run_extract()
    assert (r.ingested, r.claims, r.grounded) == (1, 2, 1)
    claims = rows(p, "SELECT package, grounded, versions_json, notes_json, provider, prompt_version "
                     "FROM report_claims ORDER BY idx")
    assert claims[0][:3] == ("left-padx", 1, '["1.0.3"]') and "9.9.9" in claims[0][3]
    assert claims[1][:2] == ("made-up-pkg", 0) and claims[0][4] == "fake" and claims[0][5]
    assert rows(p, "SELECT status, claims, grounded_claims, about_specific_packages FROM report_extractions") == [
        ("done", 2, 1, 1)]
    assert not exchange.list_ids(dirs.in_dir) and not exchange.list_ids(dirs.out_dir)  # 受け渡しのファイルは消す

    # 記事が更新されたら抽出し直し、主張は入れ替える
    add_report(p, 1, MALWARE + " Version 1.0.4 is also affected.", h="b")
    p.run_extract()
    assert rows(p, "SELECT COUNT(*) FROM report_claims") == [(0,)]
    extract(dirs, lambda _i: {"about_specific_packages": True, "claims": [{**CLAIM, "versions": ["1.0.4"]}]})
    p.run_extract()
    assert rows(p, f"SELECT versions_json FROM report_claims WHERE report_id = '{rid}'") == [('["1.0.4"]',)]


def test_failures_are_retried_then_given_up(env):
    p, dirs = env
    add_report(p, 1, MALWARE)
    p.run_extract()

    def bad(_):
        raise ExtractionFailed("no structured_output")

    for attempt in range(1, extraction.MAX_ATTEMPTS + 1):
        extract(dirs, bad)
        r = p.run_extract()
        if attempt < extraction.MAX_ATTEMPTS:
            assert r.retried == 1 and len(exchange.list_ids(dirs.in_dir)) == 1  # 次の夜にやり直す
    assert r.failed == 1 and not exchange.list_ids(dirs.in_dir)
    assert rows(p, "SELECT status, attempts, error FROM report_extractions") == [
        ("failed", 3, "no structured_output")]


def test_invalid_output_counts_as_failure(env):
    p, dirs = env
    add_report(p, 1, MALWARE)
    p.run_extract()
    [jid] = exchange.list_ids(dirs.in_dir)
    exchange.write_result(dirs.out_dir, exchange.JobResult(jid, "fake", "m", "v", NOW, {"claims": "nope"}))
    r = p.run_extract()
    assert r.retried == 1 and rows(p, "SELECT attempts FROM report_extractions") == [(1,)]


def test_stale_and_missing_job_files_are_synced(env):
    p, dirs = env
    add_report(p, 1, MALWARE)
    p.run_extract()
    [old] = exchange.list_ids(dirs.in_dir)
    add_report(p, 1, MALWARE + " update", h="b")  # 本文が変わった → 古い依頼は消える
    p.run_extract()
    [new] = exchange.list_ids(dirs.in_dir)
    assert new != old

    (dirs.in_dir / f"{new}.json").unlink()  # 依頼のファイルが無くなったら書き直す
    exchange.write_result(dirs.out_dir, exchange.JobResult(old, "fake", "m", "v", NOW, None, "late"))
    p.run_extract()
    assert exchange.list_ids(dirs.in_dir) == [new] and not exchange.list_ids(dirs.out_dir)


def test_max_pending(env):
    p, dirs = env
    for n in range(1, 6):
        add_report(p, n, MALWARE)
    r = extraction.ExtractResult()
    extraction.queue(p.engine, dirs.in_dir, NOW, r, max_pending=3)
    assert r.queued == 3 and len(exchange.list_ids(dirs.in_dir)) == 3
    r2 = extraction.ExtractResult()
    extraction.queue(p.engine, dirs.in_dir, NOW, r2, max_pending=3)
    assert r2.queued == 0  # 待ちが減るまで依頼しない


def test_extractor_health(env):
    p, dirs = env
    now = utc_now()
    assert extractor_checks(None, None, now) == []
    [c] = extractor_checks(p.engine, dirs.state_dir, now)
    assert c.ok and c.detail == "抽出待ちなし"

    add_report(p, 1, MALWARE)
    extraction.queue(p.engine, dirs.in_dir, to_iso(now - timedelta(hours=50)), extraction.ExtractResult())
    exchange.write_json(dirs.usage_path, {"last_stopped": "CLAUDE_CODE_OAUTH_TOKEN is empty (config/llm.env)"})
    [c] = extractor_checks(p.engine, dirs.state_dir, now)
    assert not c.ok and "抽出待ち 1 件" in c.detail and "CLAUDE_CODE_OAUTH_TOKEN" in c.detail
    assert json.loads(dirs.usage_path.read_text())  # 読むだけ
