"""L4: 記事の主張の確度の判定と、照合に使う Advisory (claim_advisories) のテスト。"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from src.intel import claims
from src.intel.pipeline import IntelPipeline
from tests.intel.test_pipeline import MAL
from tests.intel.test_pipeline import env as intel_env  # noqa: F401  (fixture)

NOW = "2026-11-04T00:00:00.000000Z"


@pytest.fixture
def intel(intel_env):  # noqa: F811
    p, osv, _, _ = intel_env
    osv.zips["npm"].append(MAL | {"affected": [
        {"package": {"ecosystem": "npm", "name": "evilpkg"}, "versions": ["1.0.0"]}]})
    p.bootstrap()  # CVE-2026-1111 (PyPI examplelib)・MAL-2026-100 (npm evilpkg)
    return p, osv


def add_claim(p: IntelPipeline, n: int, package: str, *, kind: str = "malicious", eco: str = "npm",
              versions: tuple[str, ...] = (), ids: tuple[str, ...] = (), trust: str = "research",
              grounded: bool = True, report: int | None = None, quote: str | None = None) -> str:
    rid = f"rep_{report if report is not None else n:024x}"
    cid = f"clm_{n:024x}"
    with p.engine.begin() as conn:
        conn.execute(text("""
            INSERT OR IGNORE INTO reports (report_id, feed_id, guid, url, title, summary, trust, lang, initial,
              content_hash, raw_ref, first_seen_at, updated_at)
            VALUES (:r, :f, :r, 'https://ex.test/a', :title, 'x', :t, 'en', 0, :h, 'raw/x', :now, :now)
        """), {"r": rid, "f": f"{trust}-feed", "title": f"Report {n}", "t": trust, "h": "a" * 64, "now": NOW})
        conn.execute(text("""
            INSERT INTO report_claims (claim_id, report_id, content_hash, idx, ecosystem, package, versions_json,
              kind, identifiers_json, quote, grounded, notes_json, provider, model, prompt_version, extracted_at)
            VALUES (:c, :r, :h, :i, :eco, :pkg, :v, :kind, :ids, :q, :g, '[]', 'fake', 'm', 'v', :now)
        """), {"c": cid, "r": rid, "h": "a" * 64, "i": n, "eco": eco, "pkg": package, "v": json.dumps(versions),
               "kind": kind, "ids": json.dumps(ids), "g": grounded, "now": NOW,
               "q": quote if quote is not None else f"The package {package} contains malware."})
    return cid


def rows(p: IntelPipeline, sql: str) -> list[tuple]:
    with p.engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql)).all()]


def status(p: IntelPipeline) -> dict[str, tuple]:
    return {r[0]: r[1:] for r in rows(p, "SELECT package, status, status_reason, linked_json, advisory_id "
                                         "FROM report_claims")}


def test_rules(intel):
    p, _ = intel
    add_claim(p, 1, "fresh-evil", trust="official")
    add_claim(p, 2, "rumored-pkg")  # 調査会社・ID なし
    add_claim(p, 3, "renamed", ids=("MAL-2026-100",))  # ID が OSV にある
    add_claim(p, 4, "EvilPkg")  # 名前で MAL に当たる (大文字小文字は npm では区別するので当たらない)
    add_claim(p, 5, "evilpkg")
    add_claim(p, 6, "examplelib", kind="vulnerable", eco="PyPI", ids=("GHSA-aaaa-bbbb-cccc",))
    add_claim(p, 7, "examplelib", kind="vulnerable", eco="PyPI", trust="official")  # 版なし → Advisory にしない
    add_claim(p, 8, "ghost", grounded=False, trust="official")
    add_claim(p, 9, "with-id", ids=("GHSA-zzzz-zzzz-zzzz",))  # ID 付きの調査報告
    add_claim(p, 10, "acme.tool", eco="OpenVSX", kind="compromised", versions=("1.2.3",), trust="official")
    add_claim(p, 11, "mixed-up", trust="official", quote="Several packages were removed.")

    r = claims.assess(p.engine, NOW)
    s = status(p)
    assert s["fresh-evil"][:2] == ("confirmed", "公式の告知 (official-feed)")
    assert s["rumored-pkg"][:2] == ("unconfirmed", "一次情報で裏付けなし")
    assert s["renamed"][0] == "superseded" and json.loads(s["renamed"][2]) == ["MAL-2026-100"]
    assert s["EvilPkg"][0] == "unconfirmed"
    assert s["evilpkg"][0] == "superseded" and json.loads(s["evilpkg"][2]) == ["MAL-2026-100"]
    assert s["examplelib"][0] in {"superseded", "confirmed"}
    assert s["ghost"][0] == "ungrounded"
    assert s["with-id"][:2] == ("confirmed", "ID 付きの調査報告 (GHSA-zzzz-zzzz-zzzz)")
    assert s["mixed-up"][:2] == ("unconfirmed", "根拠の 1 文にパッケージ名がない")
    assert (r.confirmed, r.unconfirmed, r.superseded, r.advisories) == (4, 3, 3, 3)

    adv = {r[0]: r[1:] for r in rows(p, "SELECT name, kind, ecosystem, ranges_json, versions_json, withdrawn "
                                       "FROM claim_advisories")}
    assert adv == {
        "fresh-evil": ("malicious", "npm", json.dumps(claims.ALL_VERSIONS), None, 0),
        "with-id": ("malicious", "npm", json.dumps(claims.ALL_VERSIONS), None, 0),
        "acme.tool": ("malicious", "VSCode:https://open-vsx.org", "[]", '["1.2.3"]', 0),
    }
    # 照合の契約ビューに載る (A2 はそのまま照合できる)
    spi = s["fresh-evil"][3]
    assert spi.startswith("SPI-")
    assert rows(p, f"SELECT kind, kev, withdrawn FROM v_advisories WHERE advisory_id = '{spi}'") == [
        ("malicious", 0, 0)]
    assert rows(p, f"SELECT ecosystem, name FROM v_advisory_affected WHERE advisory_id = '{spi}'") == [
        ("npm", "fresh-evil")]
    assert {r[0] for r in rows(p, "SELECT status FROM v_report_claims")} == {
        "confirmed", "unconfirmed", "superseded", "ungrounded"}


def test_idempotent_then_superseded_by_osv(intel):
    p, osv = intel
    add_claim(p, 1, "fresh-evil", trust="official")
    add_claim(p, 2, "fresh-evil", trust="official", report=9)  # 別の記事の同じ主張は 1 件にまとめる
    claims.assess(p.engine, NOW)
    [(spi, updated, ids)] = rows(p, "SELECT advisory_id, updated_at, claim_ids_json FROM claim_advisories")
    assert len(json.loads(ids)) == 2
    claims.assess(p.engine, "2026-11-05T00:00:00.000000Z")
    assert rows(p, "SELECT updated_at FROM claim_advisories") == [(updated,)]  # 変わらなければ書かない

    # 後から OSV に悪性パッケージとして載った → OSV に任せて取り下げる
    osv.zips["npm"].append({"id": "MAL-2026-200", "modified": "2026-11-05T00:00:00Z",
                            "affected": [{"package": {"ecosystem": "npm", "name": "fresh-evil"},
                                          "versions": ["0.1.0"]}]})
    p.run_osv_full()
    r = claims.assess(p.engine, "2026-11-06T00:00:00.000000Z")
    assert (r.superseded, r.advisories, r.withdrawn) == (2, 0, 1)
    assert rows(p, "SELECT withdrawn, withdrawn_reason FROM claim_advisories") == [(1, "OSV に登録された")]
    assert {s[3] for s in status(p).values()} == {None}
    assert rows(p, f"SELECT withdrawn FROM v_advisories WHERE advisory_id = '{spi}'") == [(1,)]


def test_withdrawn_when_claim_goes_away(intel):
    p, _ = intel
    cid = add_claim(p, 1, "fresh-evil", trust="official")
    claims.assess(p.engine, NOW)
    with p.engine.begin() as conn:
        conn.execute(text("DELETE FROM report_claims WHERE claim_id = :c"), {"c": cid})
    r = claims.assess(p.engine, NOW)
    assert r.withdrawn == 1
    assert rows(p, "SELECT withdrawn, withdrawn_reason FROM claim_advisories") == [(1, "記事の主張がなくなった")]
    add_claim(p, 1, "fresh-evil", trust="official")  # また載れば取り下げを戻す
    claims.assess(p.engine, NOW)
    assert rows(p, "SELECT withdrawn FROM claim_advisories") == [(0,)]


def test_compromised_versions_and_names():
    assert claims.osv_ecosystem("OpenVSX") == "VSCode:https://open-vsx.org"
    assert claims.osv_ecosystem("Docker") is None and claims.osv_ecosystem("PyPI") == "PyPI"
    assert claims.name_key("PyPI", "Foo_Bar.baz") == "foo-bar-baz"
    assert claims.name_key("VSCode:https://open-vsx.org", "Acme.Tool") == "acme.tool"
    assert claims.name_key("npm", "Left-Pad") == "Left-Pad"


def test_compromised_other_versions_is_not_superseded(intel):
    p, _ = intel
    add_claim(p, 1, "evilpkg", kind="compromised", versions=("2.0.0",), trust="official")
    add_claim(p, 2, "evilpkg", kind="compromised", versions=("1.0.0",), trust="official", report=1)
    claims.assess(p.engine, NOW)
    by_id = {r[0]: r[1] for r in rows(p, "SELECT versions_json, status FROM report_claims")}
    assert by_id == {'["2.0.0"]': "confirmed", '["1.0.0"]': "superseded"}  # MAL-2026-100 は 1.0.0 だけ


def test_claims_cli(intel, monkeypatch):
    from typer.testing import CliRunner

    from src.intel import __main__ as cli

    p, _ = intel
    add_claim(p, 1, "fresh-evil", trust="official")
    add_claim(p, 2, "ghost", grounded=False)
    claims.assess(p.engine, NOW)
    monkeypatch.setattr(cli, "build_pipeline", lambda **_: p)
    out = CliRunner().invoke(cli.app, ["claims"]).output
    assert "confirmed   npm:fresh-evil * [malicious] SPI-" in out and "公式の告知 (official-feed)" in out
    assert "ghost" not in out
    assert "ungrounded" in CliRunner().invoke(cli.app, ["claims", "--all"]).output


def test_version_ranges_become_advisory(intel):
    """記事の範囲の書き方 ("earlier than 1.84.1") を range と修正版にする。"""
    p, _ = intel
    add_claim(p, 1, "examplegrpc", kind="vulnerable", eco="PyPI", versions=("earlier than 1.84.1",),
              trust="official", quote="examplegrpc earlier than 1.84.1 (gRPC transports); bundled root store.")
    add_claim(p, 2, "google-api-services-*", kind="vulnerable", eco="Maven", trust="official",
              versions=("version suffix earlier than -2.9.2",), quote="google-api-services-* suffix earlier.")
    r = claims.assess(p.engine, NOW)
    assert r.advisories == 1  # 解釈できない書き方の版しかないものは Advisory にしない
    [(name, ranges, versions, fixed)] = rows(p, "SELECT name, ranges_json, versions_json, fixed_json "
                                                "FROM claim_advisories")
    assert name == "examplegrpc" and versions == "[]" and fixed == '["1.84.1"]'
    assert json.loads(ranges) == [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "1.84.1"}]}]
    assert rows(p, "SELECT fixed_json FROM v_advisory_affected WHERE name = 'examplegrpc'") == [('["1.84.1"]',)]
