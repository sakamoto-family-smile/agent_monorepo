"""Claude Agent SDK に渡す接続先・認証・ツールの設定 (PROPOSAL-0014)。

gateway (LiteLLM) を使うときは、バーチャルキーと分析ごとの trace ID をヘッダで送る。
gateway は trace ID を Langfuse の session ID にするので、分析 1 回 = 1 セッションになる。
"""

from __future__ import annotations

import json
import os
import uuid

from config import Settings

# bypassPermissions では allowed_tools が使えるツールを絞らないため、使わせないものを明示する。
# 分析に要るのは Read / Glob / Grep と Brave Search の MCP だけ。
DISALLOWED_TOOLS: tuple[str, ...] = (
    "Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch", "Task",
)


def new_trace_id() -> str:
    """gateway が受け付ける 32 桁の 16 進。"""
    return uuid.uuid4().hex


def uses_gateway(settings: Settings) -> bool:
    return bool(settings.llm_gateway_url)


def claude_env(settings: Settings, trace_id: str) -> dict[str, str]:
    """CLI に渡す環境変数。ANTHROPIC_AUTH_TOKEN は渡さない (定額プランのトークンの代わりに送られる)。"""
    env = {
        # claude_agent_sdk は HOME を必要とする。docker / Cloud Run でも
        # /tmp は書込可能なため恒常的にここを使う。本物のシークレット保存先
        # ではないので bandit B108 を抑止する。
        "HOME": "/tmp",  # nosec B108
        "ANTHROPIC_API_KEY": "",
        "CLAUDE_CODE_OAUTH_TOKEN": os.getenv("CLAUDE_CODE_OAUTH_TOKEN", ""),
        "BRAVE_API_KEY": os.getenv("BRAVE_API_KEY", ""),
    }
    if uses_gateway(settings):
        if not settings.llm_gateway_key:
            raise RuntimeError("LLM_GATEWAY_URL を使うには LLM_GATEWAY_KEY が必要です")
        env["ANTHROPIC_BASE_URL"] = settings.llm_gateway_url
        env["ANTHROPIC_CUSTOM_HEADERS"] = (
            f"x-litellm-api-key: Bearer {settings.llm_gateway_key}\n"
            f"x-litellm-trace-id: {trace_id}"
        )
    return env


def claude_settings(settings: Settings) -> str | None:
    """gateway のときは LLM_MODEL を別名に対応付ける。

    対応付けがないと CLI は別名を未知のモデルとして扱い、毎回 1 本目が 400 になって送り直す。
    """
    if not uses_gateway(settings):
        return None
    return json.dumps({"modelOverrides": {settings.llm_model: settings.llm_gateway_model}})


def model_label(settings: Settings) -> str:
    """レポートに残すモデル名。gateway のときは別名 (実体は gateway の設定とトレースで分かる)。"""
    return settings.llm_gateway_model if uses_gateway(settings) else settings.llm_model
