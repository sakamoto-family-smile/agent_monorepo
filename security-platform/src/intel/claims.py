"""L4: 記事の主張の確度を決まったルールで判定し、confirmed を照合に使う Advisory にする (extract ジョブの中)。

LLM は記事から抜き出すだけで、確からしさはここで決める (要件 R9〜R11)。

| status | 条件 | 使い道 |
|---|---|---|
| ungrounded | 根拠の 1 文・パッケージ名が記事にない (grounding.py) | 評価のために残すだけ |
| superseded | 記事の ID (CVE・GHSA・MAL) か、同じパッケージの悪性パッケージの登録が OSV にある | 照合は OSV に任せる |
| confirmed | 公式の告知 (trust = official) で根拠の 1 文にパッケージ名があるもの、または ID 付きの調査会社の報告 | claim_advisories に載せて照合する |
| unconfirmed | それ以外 | 照合しない。使っているパッケージと同じ名前なら早期警告 (A2) |

confirmed の主張は (エコシステム, パッケージ, 悪性か脆弱か) ごとに 1 件の Advisory (``SPI-...``) にまとめ、
v_advisories・v_advisory_affected に載せる。悪性 (malicious) は全版、侵害 (compromised)・脆弱 (vulnerable) は
記事にある版だけを照合する。版は記事の書き方 ("earlier than 1.84.1" など) を claim_versions.py で個別の版と
range に直す (版の無い・解釈できない侵害・脆弱は照合できないので Advisory にしない)。
後から OSV に載ったり記事の主張が無くなったりしたら Advisory を取り下げ (withdrawn)、Finding は次の照合で閉じる。
superseded と ungrounded は判定し直さない (OSV に載ったものは OSV が正)。
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import Connection, Engine, bindparam, text

from ..detection.lockfiles import canonical_pypi_name
from ..detection.versions import is_affected
from ..llm.grounding import normalize
from .claim_versions import parse as parse_versions

CONFIRMED = "confirmed"
UNCONFIRMED = "unconfirmed"
SUPERSEDED = "superseded"
UNGROUNDED = "ungrounded"

# 抽出のエコシステム名 → OSV の表記。照合できないもの (Docker・other) は None
OSV_ECOSYSTEM = {"OpenVSX": "VSCode:https://open-vsx.org", "Docker": None, "other": None}
ALL_VERSIONS = [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}]}]
SUMMARY_MAX = 300


def osv_ecosystem(ecosystem: str) -> str | None:
    return OSV_ECOSYSTEM.get(ecosystem, ecosystem)


def name_key(ecosystem: str, name: str) -> str:
    """同じパッケージとみなす名前 (PyPI は PEP 503、拡張の ID・GitHub Actions は大文字小文字を区別しない)。"""
    if ecosystem == "PyPI":
        return canonical_pypi_name(name)
    if ecosystem.startswith("VSCode") or ecosystem == "GitHub Actions":
        return name.lower()
    return name


def advisory_kind(kind: str) -> str:
    return "vulnerability" if kind == "vulnerable" else "malicious"


@dataclass
class AssessResult:
    confirmed: int = 0
    unconfirmed: int = 0
    superseded: int = 0
    advisories: int = 0  # 照合に使う (取り下げていない) claim_advisories
    withdrawn: int = 0  # 今回取り下げた claim_advisories
    by_status: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class _Claim:
    claim_id: str
    ecosystem: str
    package: str
    versions: tuple[str, ...]
    kind: str
    identifiers: tuple[str, ...]
    quote: str
    grounded: bool
    trust: str
    feed_id: str
    title: str
    first_seen_at: str


def _load(conn: Connection, *, pending: bool) -> list[_Claim]:
    """pending: 判定し直す主張 (confirmed・unconfirmed と未判定)。False なら confirmed だけ。

    記事が更新されて抽出し直している間は、前の本文から抜き出した主張を使い続ける。
    """
    where = "c.status IN (:c, :u) OR c.assessed_at IS NULL" if pending else "c.status = :c AND c.grounded = 1"
    rows = conn.execute(text(f"""
        SELECT c.claim_id, c.ecosystem, c.package, c.versions_json, c.kind, c.identifiers_json, c.quote, c.grounded,
          r.trust, r.feed_id, r.title, r.first_seen_at
        FROM report_claims c JOIN reports r ON r.report_id = c.report_id
        WHERE {where}
        ORDER BY r.first_seen_at, c.claim_id
    """), {"c": CONFIRMED, "u": UNCONFIRMED}).all()  # nosec B608  where は固定の条件
    return [_Claim(r[0], r[1], r[2], tuple(json.loads(r[3])), r[4], tuple(json.loads(r[5])), r[6], bool(r[7]),
                   r[8], r[9], r[10], r[11]) for r in rows]


# ── OSV との対応付け ──────────────────────────────────────────────────────
def _by_identifiers(conn: Connection, ids: tuple[str, ...]) -> set[str]:
    if not ids:
        return set()
    stmt = text("""
        SELECT advisory_id FROM advisories WHERE advisory_id IN :ids
        UNION SELECT advisory_id FROM osv_records WHERE record_id IN :ids
        UNION SELECT r.advisory_id FROM record_aliases x JOIN osv_records r ON r.record_id = x.record_id
          WHERE x.alias IN :ids
    """).bindparams(bindparam("ids", expanding=True))
    return set(conn.execute(stmt, {"ids": list(ids)}).scalars().all())


def _by_package(conn: Connection, c: _Claim, eco: str) -> set[str]:
    """同じパッケージの悪性パッケージの登録 (MAL)。侵害は記事の版のどれかが含まれるものだけ。脆弱は ID でだけ対応付ける。"""
    if c.kind == "vulnerable":
        return set()
    rows = conn.execute(text("""
        SELECT a.advisory_id, f.name, f.ranges_json, f.versions_json
        FROM record_affected f JOIN osv_records r ON r.record_id = f.record_id
        JOIN advisories a ON a.advisory_id = r.advisory_id
        WHERE a.kind = 'malicious' AND f.ecosystem = :e AND LOWER(f.name) = LOWER(:n)
    """), {"e": eco, "n": c.package}).all()
    key = name_key(eco, c.package)
    exact = parse_versions(eco, c.versions).exact
    out = set()
    for adv, name, ranges, versions in rows:
        if name_key(eco, name) != key:
            continue
        if c.kind == "compromised" and exact and not any(
            is_affected(eco, v, json.loads(ranges), json.loads(versions or "[]")) for v in exact
        ):
            continue  # 別の版の侵害の登録
        out.add(adv)
    return out


def _judge(conn: Connection, c: _Claim) -> tuple[str, str, list[str]]:
    if not c.grounded:
        return UNGROUNDED, "原文に根拠なし", []
    eco = osv_ecosystem(c.ecosystem)
    linked = _by_identifiers(conn, c.identifiers)
    if eco is not None:
        linked |= _by_package(conn, c, eco)
    if linked:
        return SUPERSEDED, "OSV に登録済み", sorted(linked)
    if c.trust == "official" and normalize(c.package) in normalize(c.quote):
        # 記事の別のパッケージの話を取り違えていないよう、根拠の 1 文にパッケージ名があるものだけ
        return CONFIRMED, f"公式の告知 ({c.feed_id})", []
    if c.trust == "research" and c.identifiers:
        return CONFIRMED, f"ID 付きの調査報告 ({', '.join(c.identifiers)})", []
    if c.trust == "official":
        return UNCONFIRMED, "根拠の 1 文にパッケージ名がない", []
    return UNCONFIRMED, "一次情報で裏付けなし", []


# ── 照合に使う Advisory ───────────────────────────────────────────────────
@dataclass
class _Advisory:
    advisory_id: str
    kind: str
    ecosystem: str
    name: str
    versions: set[str] = field(default_factory=set)
    ranges: list[dict[str, object]] = field(default_factory=list)
    claims: list[_Claim] = field(default_factory=list)
    all_versions: bool = False  # 悪性 (malicious) の主張があればパッケージごと

    def row(self, now: str) -> dict[str, object]:
        first = self.claims[0]
        label = "悪性・侵害" if self.kind == "malicious" else "脆弱性"
        summary = f"記事から ({label}): {self.name} — {first.title}"[:SUMMARY_MAX]
        return {
            "id": self.advisory_id, "kind": self.kind, "eco": self.ecosystem, "name": self.name,
            "ranges": json.dumps(ALL_VERSIONS if self.all_versions else self.ranges),
            "fixed": json.dumps([] if self.all_versions else sorted(
                {v for r in self.ranges for ev in r["events"] for k, v in ev.items() if k == "fixed"})),
            "versions": None if self.all_versions else json.dumps(sorted(self.versions)),
            "summary": summary, "claims": json.dumps(sorted(c.claim_id for c in self.claims)),
            "first": min(c.first_seen_at for c in self.claims), "now": now,
        }


def _advisory_id(eco: str, key: str, kind: str) -> str:
    return "SPI-" + hashlib.sha256(f"{eco}\n{key}\n{kind}".encode()).hexdigest()[:16].upper()


def _materialize(claims: list[_Claim]) -> dict[str, _Advisory]:
    out: dict[str, _Advisory] = {}
    for c in claims:
        eco = osv_ecosystem(c.ecosystem)
        if eco is None:
            continue
        parsed = parse_versions(eco, c.versions)
        if c.kind != "malicious" and not parsed.matchable:
            continue
        kind = advisory_kind(c.kind)
        adv_id = _advisory_id(eco, name_key(eco, c.package), kind)
        adv = out.setdefault(adv_id, _Advisory(adv_id, kind, eco, c.package))
        adv.versions.update(parsed.exact)
        adv.ranges.extend(r for r in parsed.ranges if r not in adv.ranges)
        adv.all_versions = adv.all_versions or c.kind == "malicious"
        adv.claims.append(c)
    return out


def _withdrawn_reason(conn: Connection, claim_ids: str, superseded: int) -> str:
    if superseded:
        return "OSV に登録された"
    left = conn.execute(text(
        "SELECT COUNT(*) FROM report_claims WHERE status = :c AND claim_id IN (SELECT value FROM json_each(:ids))"
    ), {"c": CONFIRMED, "ids": claim_ids}).scalar_one()
    return "照合できる版がない" if left else "記事の主張がなくなった"


def _sync_advisories(conn: Connection, desired: dict[str, _Advisory], now: str, result: AssessResult) -> None:
    existing = {r[0]: (r[1], r[2], r[3], r[4], r[5], bool(r[6])) for r in conn.execute(text(
        "SELECT advisory_id, ranges_json, versions_json, summary, claim_ids_json, fixed_json, withdrawn "
        "FROM claim_advisories"
    )).all()}
    for adv_id, adv in desired.items():
        row = adv.row(now)
        prev = existing.get(adv_id)
        if prev is not None and not prev[5] and prev[:5] == (
                row["ranges"], row["versions"], row["summary"], row["claims"], row["fixed"]):
            continue
        conn.execute(text("""
            INSERT INTO claim_advisories (advisory_id, kind, ecosystem, name, ranges_json, versions_json, fixed_json,
              summary, claim_ids_json, withdrawn, withdrawn_reason, first_seen_at, updated_at)
            VALUES (:id, :kind, :eco, :name, :ranges, :versions, :fixed, :summary, :claims, 0, NULL, :first, :now)
            ON CONFLICT(advisory_id) DO UPDATE SET ranges_json = excluded.ranges_json,
              versions_json = excluded.versions_json, fixed_json = excluded.fixed_json, summary = excluded.summary,
              claim_ids_json = excluded.claim_ids_json, withdrawn = 0, withdrawn_reason = NULL,
              updated_at = excluded.updated_at
        """), row)
    for adv_id, prev in existing.items():
        if adv_id in desired or prev[5]:
            continue
        superseded = conn.execute(text(
            "SELECT COUNT(*) FROM report_claims WHERE status = :s AND claim_id IN (SELECT value FROM json_each(:ids))"
        ), {"s": SUPERSEDED, "ids": prev[3]}).scalar_one()
        conn.execute(text(
            "UPDATE claim_advisories SET withdrawn = 1, withdrawn_reason = :r, updated_at = :now "
            "WHERE advisory_id = :id"
        ), {"r": _withdrawn_reason(conn, prev[3], superseded), "now": now, "id": adv_id})
        result.withdrawn += 1
    result.advisories = conn.execute(
        text("SELECT COUNT(*) FROM claim_advisories WHERE withdrawn = 0")).scalar_one()


def assess(engine: Engine, now: str) -> AssessResult:
    result = AssessResult()
    with engine.begin() as conn:
        for c in _load(conn, pending=True):
            status, reason, linked = _judge(conn, c)
            conn.execute(text("""
                UPDATE report_claims SET status = :s, status_reason = :r, linked_json = :l, assessed_at = :now
                WHERE claim_id = :id
            """), {"s": status, "r": reason, "l": json.dumps(linked), "now": now, "id": c.claim_id})
        desired = _materialize(_load(conn, pending=False))
        mapped = {c.claim_id: adv_id for adv_id, adv in desired.items() for c in adv.claims}
        conn.execute(text("UPDATE report_claims SET advisory_id = NULL WHERE advisory_id IS NOT NULL"))
        for claim_id, adv_id in mapped.items():
            conn.execute(text("UPDATE report_claims SET advisory_id = :a WHERE claim_id = :id"),
                         {"a": adv_id, "id": claim_id})
        _sync_advisories(conn, desired, now, result)
        counts = defaultdict(int, {r[0]: r[1] for r in conn.execute(
            text("SELECT status, COUNT(*) FROM report_claims GROUP BY status")).all()})
    result.by_status = dict(counts)
    result.confirmed, result.unconfirmed, result.superseded = counts[CONFIRMED], counts[UNCONFIRMED], \
        counts[SUPERSEDED]
    return result
