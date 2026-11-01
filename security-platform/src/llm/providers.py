"""抽出に使う LLM の差し替え口。LLM_PROVIDER で選ぶ。

    claude-code  Claude Code の CLI (claude -p) を Max プランの長期トークン (CLAUDE_CODE_OAUTH_TOKEN) で動かす
    fake         テスト・配線の確認用 (何も抜き出さない)
    anthropic / gemini  L4 PR4 で追加する (API キーで従量課金)

どのプロバイダも ExtractInput を受け取り、schema.OUTPUT_SCHEMA の形の dict を返す。
有料のプロバイダへ自動では切り替えない (Max プランの上限に達したら、その夜は止める)。
"""
from __future__ import annotations

import json
import os
import subprocess  # nosec B404 - 固定の引数で claude を呼ぶだけ (シェルを通さない)
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .schema import OUTPUT_SCHEMA, SYSTEM_PROMPT, ExtractInput, validate_output

PROVIDERS = ("claude-code", "fake", "anthropic", "gemini")


class ProviderUnavailable(RuntimeError):
    """認証の失敗・利用上限・LLM 側の障害。この記事に限らないので、その回の処理を止める。"""


class ExtractionFailed(RuntimeError):
    """この記事だけの失敗 (出力の形が違う・時間切れなど)。"""


class Extractor(Protocol):
    provider: str
    model: str

    def extract(self, item: ExtractInput) -> dict[str, Any]: ...


# ── Claude Code (Max プラン) ──────────────────────────────────────────────
# 子プロセスに渡す環境変数はこれだけ。ANTHROPIC_API_KEY があると -p ではそちらが優先されて
# 従量課金になるので、絶対に渡さない
_PASS_ENV = ("PATH", "HOME", "LANG", "TZ")
_QUIET_ENV = {
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",  # 自動更新・テレメトリ・エラー報告を止める
    "DISABLE_AUTOUPDATER": "1",
}
_UNAVAILABLE_STATUS = {401, 403, 429, 500, 502, 503, 529}


@dataclass
class ClaudeCodeExtractor:
    token: str
    model: str = "haiku"
    binary: str = "claude"
    timeout_seconds: float = 180.0
    max_budget_usd: float = 0.05  # 1 記事あたりの上限 (Haiku なら 1 記事 0.01 ドル未満)
    provider: str = field(default="claude-code", init=False)

    def command(self) -> list[str]:
        """道具 (ファイル・シェル・Web)・MCP・設定ファイル・セッションの保存をすべて切る。
        --bare は CLAUDE_CODE_OAUTH_TOKEN を読まないので使わない。"""
        return [
            self.binary, "-p",
            "--output-format", "json",
            "--model", self.model,
            "--tools", "",
            "--strict-mcp-config",
            "--setting-sources", "",
            "--no-session-persistence",
            "--max-budget-usd", str(self.max_budget_usd),
            "--system-prompt", SYSTEM_PROMPT,
            "--json-schema", json.dumps(OUTPUT_SCHEMA, separators=(",", ":")),
        ]

    def env(self) -> dict[str, str]:
        env = {k: os.environ[k] for k in _PASS_ENV if k in os.environ}
        return {**env, **_QUIET_ENV, "CLAUDE_CODE_OAUTH_TOKEN": self.token}

    def extract(self, item: ExtractInput) -> dict[str, Any]:
        if not self.token:
            raise ProviderUnavailable("CLAUDE_CODE_OAUTH_TOKEN is empty (config/llm.env)")
        with tempfile.TemporaryDirectory(prefix="extract-") as cwd:  # プロジェクトの CLAUDE.md などを読ませない
            try:
                proc = subprocess.run(  # nosec B603
                    self.command(), input=item.prompt(), capture_output=True, text=True,
                    timeout=self.timeout_seconds, env=self.env(), cwd=cwd, check=False,
                )
            except subprocess.TimeoutExpired:
                raise ExtractionFailed(f"claude timed out after {self.timeout_seconds:.0f}s") from None
            except FileNotFoundError:
                raise ProviderUnavailable(f"{self.binary} is not installed") from None
        return parse_claude_output(proc.returncode, proc.stdout, proc.stderr)


def parse_claude_output(returncode: int, stdout: str, stderr: str) -> dict[str, Any]:
    try:
        out = json.loads(stdout)
    except json.JSONDecodeError:
        msg = (stderr or stdout).strip()[-500:]
        raise ProviderUnavailable(f"claude exited {returncode} without JSON: {msg}") from None
    if not isinstance(out, dict):
        raise ExtractionFailed("claude output is not an object")
    if out.get("is_error"):
        status = out.get("api_error_status")
        detail = f"claude error ({out.get('subtype')}, status {status}): {str(out.get('result'))[:300]}"
        if status in _UNAVAILABLE_STATUS:
            raise ProviderUnavailable(detail)
        raise ExtractionFailed(detail)
    if out.get("structured_output") is None:
        raise ExtractionFailed(f"claude returned no structured_output ({out.get('subtype')})")
    try:
        return validate_output(out["structured_output"])
    except ValueError as e:
        raise ExtractionFailed(f"invalid output: {e}") from None


# ── テスト用 ──────────────────────────────────────────────────────────────
@dataclass
class FakeExtractor:
    respond: Callable[[ExtractInput], dict[str, Any]] = lambda _item: {
        "about_specific_packages": False, "claims": []}
    model: str = "fake"
    provider: str = field(default="fake", init=False)

    def extract(self, item: ExtractInput) -> dict[str, Any]:
        return validate_output(self.respond(item))


def make_extractor(provider: str, model: str, *, token: str = "", binary: str = "claude") -> Extractor:
    if provider == "claude-code":
        return ClaudeCodeExtractor(token=token, model=model or "haiku", binary=binary)
    if provider == "fake":
        return FakeExtractor()
    if provider in ("anthropic", "gemini"):
        raise NotImplementedError(f"LLM_PROVIDER={provider} は L4 PR4 で追加します")
    raise ValueError(f"unknown LLM_PROVIDER: {provider!r} ({' / '.join(PROVIDERS)})")
