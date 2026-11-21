"""重大ニュース (PROPOSAL-0015) の対象の選び方と、LINE の文の組み立て。

intel.db は読み取り専用で開き、report_extractions の brief (重大度・日本語の要約・分類) と kev_entries を読むだけ。
何を・どの順で載せるかはここで決まった規則で決める (LLM には分類だけを選ばせている)。

- 記事: 重大度が critical / high のもの。同じ CVE / GHSA を持つ記事は 1 件にまとめる
- 並べ方: 重大度 → 使っている技術に関係あり → 公式・調査会社・報道の順 → 新しい順
- KEV: 追加されたものは全部 (LLM を通さない)。関係ある製品を上に
- URL はフィードに書かれた元記事のものだけを使う (LLM の出力からは取らない)
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError

from ..common.timeutil import parse_iso, to_iso
from ..llm.schema import TOPICS

ARTICLE_WINDOW = timedelta(days=7)  # これより前に要約が付いた記事は、日次では扱わない (週次で扱う)
KEV_WINDOW_DAYS = 3  # KEV の追加日 (米国の日付) から何日以内を日次で扱うか
KEV_LIST_LIMIT = 7
NEWS_SEVERITIES = ("critical", "high")
SEVERITY_LABELS = {"critical": "重大", "high": "高", "medium": "中", "low": "低", "none": "-"}
TRUST_ORDER = {"official": 0, "research": 1, "news": 2}


@dataclass(frozen=True)
class NewsConfig:
    stack: frozenset[str]
    kev_keywords: tuple[str, ...]

    def article_relevant(self, topics: Iterable[str]) -> tuple[str, ...]:
        return tuple(t for t in topics if t in self.stack)

    def kev_relevant(self, vendor: str | None, product: str | None) -> bool:
        haystack = f"{vendor or ''} {product or ''}".lower()
        return any(k.lower() in haystack for k in self.kev_keywords)


def load_news_config(path: Path) -> NewsConfig:
    data = yaml.safe_load(path.read_text()) or {}
    stack = [str(t) for t in data.get("stack") or []]
    unknown = sorted(set(stack) - set(TOPICS))
    if unknown:
        raise ValueError(f"{path}: stack に知らない topic があります: {unknown} (src/llm/schema.py の TOPICS から選ぶ)")
    keywords = tuple(str(k).strip() for k in data.get("kev_keywords") or [] if str(k).strip())
    return NewsConfig(frozenset(stack), keywords)


@dataclass(frozen=True)
class Article:
    report_id: str
    feed_id: str
    trust: str
    title: str
    url: str | None
    severity: str
    summary_ja: str
    topics: tuple[str, ...]
    identifiers: tuple[str, ...]
    briefed_at: datetime

    @property
    def key(self) -> str:
        return f"report:{self.report_id}"


@dataclass(frozen=True)
class Kev:
    cve: str
    vendor: str | None
    product: str | None
    name: str | None
    date_added: str
    ransomware: str | None

    @property
    def key(self) -> str:
        return f"kev:{self.cve}"


@dataclass(frozen=True)
class ArticleGroup:
    """同じ出来事 (同じ CVE / GHSA) の記事のまとまり。lead を載せ、残りは「ほか n 件」にする。"""
    lead: Article
    others: tuple[Article, ...]
    relevant: tuple[str, ...]

    @property
    def severity(self) -> str:
        return self.lead.severity

    @property
    def articles(self) -> tuple[Article, ...]:
        return (self.lead, *self.others)


@dataclass(frozen=True)
class Selection:
    groups: tuple[ArticleGroup, ...]  # 載せる記事
    overflow: tuple[ArticleGroup, ...]  # 載せきれなかった記事 (扱い済みにする)
    kev: tuple[Kev, ...]
    kev_overflow: tuple[Kev, ...]
    relevant_kev: frozenset[str]

    @property
    def empty(self) -> bool:
        return not self.groups and not self.kev

    def keys(self) -> list[tuple[str, bool]]:
        """(item_key, 本文に載せたか)。"""
        shown = [a.key for g in self.groups for a in g.articles] + [k.key for k in self.kev]
        hidden = [a.key for g in self.overflow for a in g.articles] + [k.key for k in self.kev_overflow]
        return [(k, True) for k in shown] + [(k, False) for k in hidden]


# ── 読み込み ──────────────────────────────────────────────────────────────
def load_articles(intel: Engine, since: datetime, until: datetime | None = None,
                  severities: tuple[str, ...] = NEWS_SEVERITIES) -> list[Article]:
    """since 以降 (until より前) に brief が付いた記事。intel.db が PROPOSAL-0015 より前なら空。"""
    marks = ", ".join(f":s{i}" for i in range(len(severities)))
    sql = ("SELECT r.report_id, r.feed_id, r.trust, r.title, r.url, e.severity, e.summary_ja, e.topics_json, "
           "e.brief_identifiers_json, e.finished_at FROM report_extractions e "
           "JOIN reports r ON r.report_id = e.report_id AND r.content_hash = e.content_hash "
           f"WHERE e.status = 'done' AND e.severity IN ({marks}) AND e.finished_at >= :since "  # nosec B608  固定の条件
           + ("AND e.finished_at < :until " if until else "")
           + "ORDER BY e.finished_at, r.report_id")
    params: dict[str, Any] = {"since": to_iso(since), **{f"s{i}": v for i, v in enumerate(severities)}}
    if until:
        params["until"] = to_iso(until)
    try:
        with intel.connect() as conn:
            rows = conn.execute(text(sql), params).all()
    except OperationalError:
        return []
    return [Article(r[0], r[1], r[2], r[3], r[4], r[5], r[6], tuple(json.loads(r[7] or "[]")),
                    tuple(json.loads(r[8] or "[]")), parse_iso(r[9])) for r in rows]


def load_kev(intel: Engine, since: date, until: date | None = None) -> list[Kev]:
    """追加日が since 以降 (until より前) の KEV。"""
    sql = ("SELECT cve, vendor, product, name, date_added, ransomware FROM kev_entries "
           "WHERE date_added >= :since" + (" AND date_added < :until" if until else "")
           + " ORDER BY date_added DESC, cve")
    params = {"since": since.isoformat(), **({"until": until.isoformat()} if until else {})}
    try:
        with intel.connect() as conn:
            rows = conn.execute(text(sql), params).all()
    except OperationalError:
        return []
    return [Kev(*r) for r in rows]


# ── 選び方 ────────────────────────────────────────────────────────────────
def _lead_order(a: Article) -> tuple[int, int, float]:
    return (NEWS_SEVERITIES.index(a.severity) if a.severity in NEWS_SEVERITIES else len(NEWS_SEVERITIES),
            TRUST_ORDER.get(a.trust, len(TRUST_ORDER)), -a.briefed_at.timestamp())


def group_articles(articles: list[Article], cfg: NewsConfig) -> list[ArticleGroup]:
    """CVE / GHSA を 1 つでも共有する記事をまとめ、決まった順に並べる。"""
    parent = list(range(len(articles)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner: dict[str, int] = {}
    for i, a in enumerate(articles):
        for ident in a.identifiers:
            if ident in owner:
                parent[find(i)] = find(owner[ident])
            else:
                owner[ident] = i
    members: dict[int, list[Article]] = {}
    for i, a in enumerate(articles):
        members.setdefault(find(i), []).append(a)
    groups = []
    for arts in members.values():
        ordered = sorted(arts, key=_lead_order)
        relevant = tuple(dict.fromkeys(t for a in ordered for t in cfg.article_relevant(a.topics)))
        groups.append(ArticleGroup(ordered[0], tuple(ordered[1:]), relevant))
    return sorted(groups, key=lambda g: (_lead_order(g.lead)[0], not g.relevant, *_lead_order(g.lead)[1:],
                                         g.lead.report_id))


def sort_kev(kevs: list[Kev], cfg: NewsConfig) -> list[Kev]:
    """関係ある製品 → 追加日の新しい順。"""
    return sorted(kevs, key=lambda k: (not cfg.kev_relevant(k.vendor, k.product), _reverse(k.date_added), k.cve))


def _reverse(day: str) -> str:
    """YYYY-MM-DD の降順に並べるための鍵。"""
    return "".join(chr(0x7F - ord(c)) for c in day)


def select_daily(intel: Engine, handled: set[str], now: datetime, cfg: NewsConfig, limit: int,
                 tz: ZoneInfo) -> Selection:
    articles = [a for a in load_articles(intel, now - ARTICLE_WINDOW) if a.key not in handled]
    groups = group_articles(articles, cfg)
    today = now.astimezone(tz).date()
    kevs = sort_kev([k for k in load_kev(intel, today - timedelta(days=KEV_WINDOW_DAYS))
                     if k.key not in handled], cfg)
    relevant = frozenset(k.cve for k in kevs if cfg.kev_relevant(k.vendor, k.product))
    return Selection(tuple(groups[:limit]), tuple(groups[limit:]), tuple(kevs[:KEV_LIST_LIMIT]),
                     tuple(kevs[KEV_LIST_LIMIT:]), relevant)


# ── 文 ────────────────────────────────────────────────────────────────────
def kev_line(k: Kev, relevant: bool) -> str:
    name = k.name or " ".join(p for p in (k.vendor, k.product) if p) or "-"
    notes = [n for n in ("関係あり" if relevant else "", "ランサムウェアで悪用" if k.ransomware == "Known" else "") if n]
    return f"・{k.cve} {name}" + (f" ({' / '.join(notes)})" if notes else "")


def article_lines(g: ArticleGroup) -> list[str]:
    source = g.lead.feed_id + (f" ほか {len(g.others)} 件" if g.others else "")
    meta = (f"関係あり: {', '.join(g.relevant)} / " if g.relevant else "") + source
    lines = [f"・[{SEVERITY_LABELS[g.severity]}] {g.lead.summary_ja} (要約)", f"  {meta}"]
    if g.lead.url:
        lines.append(f"  {g.lead.url}")
    return lines


def daily_message(s: Selection, now: datetime, tz: ZoneInfo) -> str:
    lines = [f"【重大ニュース】{now.astimezone(tz):%Y-%m-%d}"]
    if s.kev:
        n = len(s.kev) + len(s.kev_overflow)
        lines.append(f"■ 悪用が確認された脆弱性 (CISA KEV に追加) {n} 件")
        lines += [kev_line(k, k.cve in s.relevant_kev) for k in s.kev]
        if s.kev_overflow:
            lines.append(f"  ほか {len(s.kev_overflow)} 件")
    if s.groups:
        counts = {sev: sum(1 for g in s.groups if g.severity == sev) for sev in NEWS_SEVERITIES}
        lines.append(f"■ 記事 {len(s.groups)} 件 (" + " / ".join(
            f"{SEVERITY_LABELS[sev]} {counts[sev]}" for sev in NEWS_SEVERITIES) + ")")
        for g in s.groups:
            lines += article_lines(g)
    if s.overflow:
        lines.append(f"ほか {len(s.overflow)} 件は週次まとめに載ります")
    if s.groups:
        lines.append("要約は記事を LLM が読んで作ったものです。対応の判断は元記事で確かめてください")
    return "\n".join(lines)
