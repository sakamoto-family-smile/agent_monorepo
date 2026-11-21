"""重大ニュース (PROPOSAL-0015) の選び方・文の組み立て・日次の送信のテスト。"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import text

from src.common.db import make_engine
from src.common.migrate import upgrade_all
from src.common.paths import DataPaths
from src.common.timeutil import to_iso
from src.config import BASE_DIR
from src.notify import news
from src.notify.channels import GitHubIssues, LineChannel
from src.notify.health import brief_checks
from src.notify.pipeline import NotifyPipeline, NotifySettings
from tests.notify.test_notify import FakeApis

TZ = ZoneInfo("Asia/Tokyo")
NOW = datetime(2026, 11, 23, 9, 30, tzinfo=TZ).astimezone(UTC)  # 日次まとめ (9 時) の後
CFG = news.NewsConfig(frozenset({"github-actions", "browser", "npm"}), ("Google", "Chromium"))


@pytest.fixture
def env(tmp_path: Path):
    paths = DataPaths(tmp_path / "data")
    upgrade_all(paths)
    intel = make_engine(paths.sqlite_path("intel"))
    apis = FakeApis()
    client = httpx.Client(transport=httpx.MockTransport(apis))

    def make(cfg: news.NewsConfig | None = CFG, limit: int = 5, line_token: str = "tok") -> NotifyPipeline:
        return NotifyPipeline(
            make_engine(paths.sqlite_path("notify")), lambda: None,
            lambda: make_engine(paths.sqlite_path("intel"), read_only=True), paths.sbom_images_dir,
            LineChannel(client, line_token, ["Uaaa"]), GitHubIssues(client, "", ""),
            NotifySettings(TZ, 9, "P3", timedelta(hours=1), timedelta(days=7), {}, news_config=cfg,
                           news_daily_limit=limit),
        )

    return intel, make, apis


def add_article(intel, n: int, severity: str, *, trust: str = "research", topics: tuple[str, ...] = (),
                ids: tuple[str, ...] = (), at: datetime = NOW - timedelta(hours=6), summary: str | None = None,
                url: str | None = "https://ex.test/a", prompt_version: str = "2026-11-22.1") -> str:
    rid = f"rep_{n:024x}"
    with intel.begin() as conn:
        conn.execute(text("""
            INSERT INTO reports (report_id, feed_id, guid, url, title, summary, trust, lang, initial, content_hash,
              raw_ref, first_seen_at, updated_at)
            VALUES (:r, :f, :r, :u, :title, 'x', :t, 'en', 0, :h, 'raw/x', :now, :now)
        """), {"r": rid, "f": f"{trust}-feed", "u": url, "title": f"Report {n}", "t": trust, "h": "a" * 64,
               "now": to_iso(at)})
        conn.execute(text("""
            INSERT INTO report_extractions (report_id, content_hash, job_id, status, attempts, prompt_version,
              claims, grounded_claims, severity, summary_ja, topics_json, brief_identifiers_json, finished_at,
              updated_at)
            VALUES (:r, :h, :r, 'done', 1, :pv, 0, 0, :sev, :sum, :topics, :ids, :t, :t)
        """), {"r": rid, "h": "a" * 64, "pv": prompt_version, "sev": severity,
               "sum": summary or f"記事 {n} の要約。", "topics": json.dumps(list(topics)), "ids": json.dumps(list(ids)),
               "t": to_iso(at)})
    return rid


def add_kev(intel, cve: str, vendor: str, product: str, date_added: str, ransomware: str = "Unknown") -> None:
    with intel.begin() as conn:
        conn.execute(text("""
            INSERT INTO kev_entries (cve, vendor, product, name, date_added, due_date, ransomware, short_description,
              raw_ref, updated_at)
            VALUES (:c, :v, :p, :n, :d, NULL, :rw, NULL, 'raw/kev', :t)
        """), {"c": cve, "v": vendor, "p": product, "n": f"{vendor} {product} Vulnerability", "d": date_added,
               "rw": ransomware, "t": to_iso(NOW)})


def q(p: NotifyPipeline, sql: str) -> list[tuple]:
    with p.engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql)).all()]


# ── 設定 ──────────────────────────────────────────────────────────────────
def test_news_config_in_repo_is_valid():
    cfg = news.load_news_config(BASE_DIR / "config" / "news.yaml")
    assert "github-actions" in cfg.stack and cfg.kev_relevant("Google", "Chromium V8")


def test_news_config_rejects_unknown_topic(tmp_path):
    p = tmp_path / "news.yaml"
    p.write_text("stack: [python, rails]\n")
    with pytest.raises(ValueError, match="rails"):
        news.load_news_config(p)


# ── 選び方 ────────────────────────────────────────────────────────────────
def test_grouping_and_order(env):
    intel, *_ = env
    add_article(intel, 1, "high", trust="news", topics=("windows",))
    add_article(intel, 2, "critical", trust="news", ids=("CVE-2026-1",))
    add_article(intel, 3, "critical", trust="official", ids=("CVE-2026-1", "CVE-2026-2"))  # 2 と同じ出来事
    add_article(intel, 4, "high", trust="news", ids=("CVE-2026-2",))  # 3 を介して同じ出来事
    add_article(intel, 5, "high", trust="news", topics=("github-actions",))
    add_article(intel, 6, "critical", trust="research")
    add_article(intel, 7, "medium")  # 中以下は載せない
    add_article(intel, 8, "critical", at=NOW - timedelta(days=8))  # 7 日より前

    groups = news.group_articles(news.load_articles(intel, NOW - news.ARTICLE_WINDOW), CFG)
    leads = [g.lead.report_id[-1] for g in groups]
    # 重大 (公式 → 調査会社) → 高 (関係あり → なし)
    assert leads == ["3", "6", "5", "1"]
    assert sorted(a.report_id[-1] for a in groups[0].others) == ["2", "4"]
    assert groups[2].relevant == ("github-actions",)


def test_kev_order_and_relevance():
    kevs = [news.Kev("CVE-2026-3", "Fortinet", "FortiOS", None, "2026-11-22", None),
            news.Kev("CVE-2026-4", "Google", "Chromium V8", None, "2026-11-20", "Known"),
            news.Kev("CVE-2026-5", "Ivanti", "Connect", None, "2026-11-23", None)]
    assert [k.cve for k in news.sort_kev(kevs, CFG)] == ["CVE-2026-4", "CVE-2026-5", "CVE-2026-3"]
    assert news.kev_line(kevs[1], True) == ("・CVE-2026-4 Google Chromium V8 (関係あり / ランサムウェアで悪用)")


# ── 日次の送信 ────────────────────────────────────────────────────────────
def test_daily_news_sent_once_after_digest_hour(env):
    intel, make, apis = env
    add_article(intel, 1, "critical", topics=("github-actions",), summary="人気の Action が侵害された。")
    add_kev(intel, "CVE-2026-9", "Google", "Chromium V8", "2026-11-22")
    add_kev(intel, "CVE-2025-1", "Old", "Product", "2025-01-01")  # 古い追加は載せない
    p = make()

    p.run_news(datetime(2026, 11, 23, 9, 10, tzinfo=TZ))  # 日次まとめがまだで、9 時台
    assert apis.line == []
    p.run_news(NOW + timedelta(hours=1))  # 10 時を過ぎたら日次まとめが無くても送る
    p.run_news(NOW + timedelta(hours=2))
    [body] = apis.texts()
    assert body.startswith("【重大ニュース】2026-11-23")
    assert "■ 悪用が確認された脆弱性 (CISA KEV に追加) 1 件\n・CVE-2026-9 Google Chromium V8 Vulnerability (関係あり)" in body
    assert "■ 記事 1 件 (重大 1 / 高 0)\n・[重大] 人気の Action が侵害された。 (要約)\n  関係あり: github-actions / research-feed" in body
    assert "https://ex.test/a" in body and "CVE-2025-1" not in body
    assert q(p, "SELECT kind, status FROM notifications") == [("news", "sent")]
    assert sorted(q(p, "SELECT item_key, shown FROM news_items")) == [
        ("kev:CVE-2026-9", 1), (f"report:rep_{1:024x}", 1)]

    # 翌日は、前の日に扱ったものを重ねない
    add_article(intel, 2, "high", at=NOW + timedelta(hours=20))
    p.run_news(NOW + timedelta(days=1, hours=1))
    assert len(apis.texts()) == 2
    assert "記事 2 の要約" in apis.texts()[1] and "CVE-2026-9" not in apis.texts()[1]


def test_overflow_is_marked_handled(env):
    intel, make, apis = env
    for n in range(1, 5):
        add_article(intel, n, "high")
    p = make(limit=2)
    p.run_news(NOW, force=True)
    body = apis.texts()[0]
    assert "■ 記事 2 件" in body and "ほか 2 件は週次まとめに載ります" in body
    assert q(p, "SELECT shown, COUNT(*) FROM news_items GROUP BY shown ORDER BY shown") == [(0, 2), (1, 2)]


def test_kev_only_message_has_no_llm_note(env):
    intel, make, apis = env
    add_kev(intel, "CVE-2026-9", "Fortinet", "FortiOS", "2026-11-22")
    make().run_news(NOW, force=True)
    [body] = apis.texts()
    assert "CVE-2026-9" in body and "LLM" not in body


def test_empty_day_is_recorded_without_sending(env):
    intel, make, apis = env
    add_article(intel, 1, "low")
    p = make()
    p.run_news(NOW)
    p.run_news(NOW + timedelta(hours=1))
    assert apis.line == []
    assert q(p, "SELECT kind, status FROM notifications") == [("news", "empty")]


def test_disabled_and_failure_keeps_items(env):
    intel, make, apis = env
    add_article(intel, 1, "critical")
    make(cfg=None).run_news(NOW, force=True)
    assert apis.line == []

    apis.line_status = 500
    p = make()
    with pytest.raises(Exception, match="LINE push failed"):
        p.run_news(NOW, force=True)
    assert q(p, "SELECT COUNT(*) FROM news_items") == [(0,)]  # 次の回にもう一度送る
    apis.line_status = 200
    p.run_news(NOW, force=True)
    assert len(apis.texts()) == 1


def test_message_fits_line_limit(env):
    intel, make, apis = env
    for n in range(1, 30):
        add_article(intel, n, "critical", summary="あ" * 140, url="https://ex.test/" + "x" * 200)
    for n in range(1, 20):
        add_kev(intel, f"CVE-2026-{n}", "Vendor" * 5, "Product" * 5, "2026-11-22")
    p = make()
    p.run_news(NOW, force=True)
    [body] = apis.texts()
    assert len(body) < 4900 and "ほか 12 件" in body and "ほか 24 件は週次まとめに載ります" in body


# ── 監視 ──────────────────────────────────────────────────────────────────
def test_brief_check(env):
    intel, *_ = env
    assert brief_checks(intel, NOW)[0].ok  # 抽出が少ないので判断しない
    for n in range(1, 4):
        add_article(intel, n, "high")
    with intel.begin() as conn:
        conn.execute(text("UPDATE report_extractions SET severity = NULL"))
    [c] = brief_checks(intel, NOW)
    assert not c.ok and "要約あり 0 件" in c.detail
    add_article(intel, 9, "low")
    assert brief_checks(intel, NOW)[0].ok
    # brief を出す前の指示の版の結果は数えない
    with intel.begin() as conn:
        conn.execute(text("UPDATE report_extractions SET severity = NULL, prompt_version = '2026-11-07.1'"))
    assert brief_checks(intel, NOW)[0].ok
