"""L4: 抽出のプロバイダ・原文との突き合わせ・extractor の夜間処理のテスト (LLM は呼ばない)。"""
from __future__ import annotations

import json
import os
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.llm import exchange
from src.llm.eval import CHECK_CASE, load_cases, score
from src.llm.grounding import ground
from src.llm.providers import (
    ClaudeCodeExtractor,
    ExtractionFailed,
    FakeExtractor,
    ProviderUnavailable,
    make_extractor,
    parse_claude_output,
)
from src.llm.schema import OUTPUT_SCHEMA, ExtractInput, validate_output
from src.llm.worker import LlmDirs, Window, read_usage, run_batch

CLAIM = {"ecosystem": "npm", "package": "left-padx", "versions": ["1.0.3"], "kind": "malicious",
         "identifiers": [], "quote": "contains malware that steals tokens"}
OUT = {"about_specific_packages": True, "claims": [CLAIM]}


def item(n: int = 0, text: str = "the npm package left-padx version 1.0.3 contains malware") -> ExtractInput:
    rid, h = f"rep_{n:024x}", f"{n:012x}" + "f" * 52
    return ExtractInput(exchange.job_id(rid, h), rid, h, "Malicious package", "https://ex.test/a", text)


# ── Claude Code ─────────────────────────────────────────────────────────
@pytest.fixture
def fake_claude(tmp_path: Path):
    """引数・環境変数・標準入力を記録し、決めた JSON を返す偽の claude。"""
    log = tmp_path / "calls.jsonl"
    script = tmp_path / "claude"

    def make(stdout: dict | str, code: int = 0) -> str:
        body = stdout if isinstance(stdout, str) else json.dumps(stdout)
        script.write_text(
            f"#!{sys.executable}\nimport json, os, sys\n"
            f"open({str(log)!r}, 'a').write(json.dumps({{'argv': sys.argv[1:], 'env': dict(os.environ), "
            f"'stdin': sys.stdin.read(), 'cwd': os.getcwd()}}) + '\\n')\n"
            f"sys.stdout.write({body!r})\nsys.exit({code})\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return str(script)

    make.calls = lambda: [json.loads(x) for x in log.read_text().splitlines()]  # type: ignore[attr-defined]
    return make


def test_claude_code_runs_without_tools_or_api_key(fake_claude, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-should-not-leak")
    monkeypatch.setenv("GITHUB_ISSUES_TOKEN", "ghp-should-not-leak")
    binary = fake_claude({"type": "result", "is_error": False, "subtype": "success", "structured_output": OUT})
    out = ClaudeCodeExtractor(token="oat-token", binary=binary).extract(item())
    assert out == OUT
    [call] = fake_claude.calls()
    argv, env = call["argv"], call["env"]
    assert argv[:2] == ["-p", "--output-format"] and "--bare" not in argv  # --bare はトークンを読まない
    assert argv[argv.index("--tools") + 1] == "" and argv[argv.index("--setting-sources") + 1] == ""
    assert {"--strict-mcp-config", "--no-session-persistence"} <= set(argv)
    assert json.loads(argv[argv.index("--json-schema") + 1]) == OUTPUT_SCHEMA
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "oat-token"
    assert "ANTHROPIC_API_KEY" not in env and "GITHUB_ISSUES_TOKEN" not in env  # 従量課金・他の秘密に流さない
    assert call["stdin"].startswith("<article>\nTitle: Malicious package") and "left-padx" in call["stdin"]
    assert Path(call["cwd"]).name.startswith("extract-")  # プロジェクトの外で動かす


@pytest.mark.parametrize(("stdout", "code", "exc"), [
    ({"is_error": True, "subtype": "error", "api_error_status": 429, "result": "usage limit"}, 1, ProviderUnavailable),
    ({"is_error": True, "subtype": "error", "api_error_status": 401, "result": "invalid token"}, 1, ProviderUnavailable),
    ("Invalid API key · Please run /login", 1, ProviderUnavailable),  # JSON でない
    ({"is_error": True, "subtype": "error_max_budget_usd", "api_error_status": None}, 1, ExtractionFailed),
    ({"is_error": False, "subtype": "success", "structured_output": None}, 0, ExtractionFailed),
    ({"is_error": False, "structured_output": {"about_specific_packages": True, "claims": [
        {**CLAIM, "ecosystem": "cocoa"}]}}, 0, ExtractionFailed),  # スキーマ外
])
def test_claude_code_errors(fake_claude, stdout, code, exc):
    with pytest.raises(exc):
        ClaudeCodeExtractor(token="t", binary=fake_claude(stdout, code)).extract(item())


def test_claude_code_needs_token_and_binary(tmp_path):
    with pytest.raises(ProviderUnavailable, match="CLAUDE_CODE_OAUTH_TOKEN"):
        ClaudeCodeExtractor(token="").extract(item())
    with pytest.raises(ProviderUnavailable, match="not installed"):
        ClaudeCodeExtractor(token="t", binary=str(tmp_path / "nope")).extract(item())


def test_make_extractor():
    assert make_extractor("claude-code", "", token="t").model == "haiku"
    assert make_extractor("fake", "x").provider == "fake"
    with pytest.raises(NotImplementedError):
        make_extractor("gemini", "gemini-2.5-flash")
    with pytest.raises(ValueError):
        make_extractor("openai", "x")


def test_parse_ok_and_validate():
    out = parse_claude_output(0, json.dumps({"is_error": False, "structured_output": OUT}), "")
    assert out == OUT
    with pytest.raises(ValueError):
        validate_output({"about_specific_packages": True, "claims": [{**CLAIM, "extra": 1}]})


# ── 原文との突き合わせ ──────────────────────────────────────────────────
def test_grounding():
    src = "Malicious package\nThe npm package Left-PadX version v1.0.3 contains  “malware”\nthat steals tokens (CVE-2026-1)."
    g = ground(src, {**CLAIM, "quote": 'contains "malware" that steals tokens', "versions": ["1.0.3", "1.0", "9.9.9"],
                     "identifiers": ["cve-2026-1", "GHSA-xxxx-yyyy-zzzz"]})
    assert g.grounded and g.versions == ("1.0.3",) and g.identifiers == ("CVE-2026-1",)
    assert g.notes == ("versions not in article: 1.0, 9.9.9", "identifiers not in article: GHSA-XXXX-YYYY-ZZZZ")

    made_up = ground(src, {**CLAIM, "package": "left-pad-evil"})
    assert not made_up.grounded and "package not in article" in made_up.notes
    paraphrase = ground(src, {**CLAIM, "quote": "the package steals credentials"})
    assert not paraphrase.grounded and paraphrase.notes == ("quote not in article",)


# ── extractor の夜間処理 ────────────────────────────────────────────────
@pytest.fixture
def dirs(tmp_path: Path) -> LlmDirs:
    return LlmDirs(tmp_path / "in", tmp_path / "out", tmp_path / "state")


NIGHT = datetime(2026, 11, 1, 18, 30, tzinfo=UTC)  # 3:30 JST


def test_window():
    w = Window(run_hour=3, window_hours=3)
    assert w.is_open(NIGHT) and not w.is_open(datetime(2026, 11, 1, 21, 0, tzinfo=UTC))  # 6:00 JST
    assert Window(run_hour=23, window_hours=2).is_open(datetime(2026, 11, 1, 15, 30, tzinfo=UTC))  # 0:30 JST


def test_run_batch_daily_limit_and_results(dirs):
    for n in range(4):
        exchange.write_job(dirs.in_dir, item(n))
    calls = []
    fake = FakeExtractor(lambda i: calls.append(i.job_id) or OUT)
    r = run_batch(fake, dirs, Window(daily_limit=3), NIGHT)
    assert (r.done, r.failed, r.pending, r.stopped) == (3, 0, 1, None)
    res = exchange.read_result(dirs.out_dir, item(0).job_id)
    assert res.output == OUT and res.provider == "fake" and res.error is None
    assert read_usage(dirs.usage_path)["count"] == 3

    again = run_batch(fake, dirs, Window(daily_limit=3), NIGHT)  # 同じ日はもう呼ばない
    assert (again.done, again.pending) == (0, 1) and len(calls) == 3
    next_day = run_batch(fake, dirs, Window(daily_limit=3), NIGHT.replace(day=2))
    assert next_day.done == 1 and len(calls) == 4


def test_run_batch_stops_on_unavailable_and_keeps_jobs(dirs):
    exchange.write_job(dirs.in_dir, item(0))
    exchange.write_job(dirs.in_dir, item(1))

    def boom(_):
        raise ProviderUnavailable("usage limit")

    r = run_batch(FakeExtractor(boom), dirs, Window(), NIGHT)
    assert r.stopped == "usage limit" and r.pending == 2
    assert not list(dirs.out_dir.glob("*.json")) if dirs.out_dir.exists() else True  # 次の夜にやり直す
    assert read_usage(dirs.usage_path)["last_stopped"] == "usage limit"


def test_run_batch_failures(dirs):
    for n in range(5):
        exchange.write_job(dirs.in_dir, item(n))
    broken = dirs.in_dir / f"{item(9).job_id}.json"
    broken.write_text("{broken")
    os.utime(broken, (0, 0))  # 最も古い依頼にする

    def bad(_):
        raise ExtractionFailed("no structured_output")

    r = run_batch(FakeExtractor(bad), dirs, Window(), NIGHT)
    # 壊れた依頼は LLM を呼ばずに失敗として返し、続けて 3 回失敗したら止める
    assert r.failed == 4 and r.stopped and r.stopped.startswith("3 failures in a row")
    assert exchange.read_result(dirs.out_dir, item(0).job_id).error == "no structured_output"
    assert read_usage(dirs.usage_path)["count"] == 3


def test_exchange_rejects_tampered_job(dirs):
    exchange.write_job(dirs.in_dir, item(0))
    p = dirs.in_dir / f"{item(0).job_id}.json"
    data = json.loads(p.read_text())
    p.write_text(json.dumps({**data, "report_id": "rep_" + "1" * 24}))
    with pytest.raises(ValueError):
        exchange.read_job(dirs.in_dir, item(0).job_id)
    (dirs.in_dir / "not-a-job.json").write_text("{}")
    assert exchange.list_ids(dirs.in_dir) == [item(0).job_id]


# ── 評価 ────────────────────────────────────────────────────────────────
def test_eval_cases_and_scoring():
    cases = load_cases()
    assert len({c.id for c in cases}) == len(cases) >= 8
    for c in cases:  # 期待するパッケージは記事にそのまま書かれている (grounding を通る)
        assert all(p.lower() in f"{c.title}\n{c.text}".lower() for p in c.expected), c.id

    def perfect(i: ExtractInput) -> dict:
        case = next(c for c in cases if c.text in i.text)
        claims = [{**CLAIM, "package": p, "versions": [], "quote": case.text.split(".")[0]} for p in case.expected]
        return {"about_specific_packages": bool(claims), "claims": claims}

    lines: list[str] = []
    s = score(FakeExtractor(perfect), cases, lines.append)
    assert (s.precision, s.recall, s.errors) == (1.0, 1.0, 0)
    assert CHECK_CASE.item().prompt().startswith("<article>")

    def injected(_: ExtractInput) -> dict:  # 記事の中の指示に従ってしまった場合
        return {"about_specific_packages": True, "claims": [{**CLAIM, "package": "lodash", "quote": "This week was quiet"}]}

    bad = score(FakeExtractor(injected), [c for c in cases if c.id == "prompt-injection"], lines.append)
    assert bad.fp == 1 and bad.precision == 0.0
