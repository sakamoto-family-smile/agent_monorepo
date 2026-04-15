import asyncio
import contextlib
import os
import logging
from typing import AsyncIterator, Optional
from claude_agent_sdk import query, ClaudeAgentOptions

logger = logging.getLogger(__name__)

# メッセージ間の無通信がこの秒数を超えたらタイムアウトとみなす
# claude_agent_sdk のサブプロセスが正常終了しても ResultMessage を
# 返さずハングするケースへの対策
_INTER_MESSAGE_TIMEOUT = int(os.getenv("AGENT_MESSAGE_TIMEOUT_SECONDS", "90"))


def build_system_prompt(mode: str) -> str:
    """モードに応じたシステムプロンプトを構築する"""
    prompts = {
        "research": "研究テーマ設計モードです。ユーザーの研究テーマ作成を支援してください。",
        "survey": "論文サーベイモードです。体系的な論文調査を行ってください。",
        "interview": "面接対策モードです。模擬面接を実施し、厳しめにフィードバックしてください。",
        "review": "研究計画レビューモードです。7軸評価を実施してください。",
    }
    return prompts.get(mode, prompts["research"])


async def run_agent(
    message: str,
    uid: str,
    mode: str = "research",
    session_id: Optional[str] = None,
) -> AsyncIterator[dict]:
    """Claude Agent SDKを使ってエージェントを実行する。

    claude_agent_sdk のサブプロセスがツール呼び出しを含むリクエストで
    ResultMessage を返さずにハングする既知の問題を回避するため、
    メッセージ間タイムアウトを Queue ベースで実装している。
    """
    workspace_base = os.getenv("WORKSPACE_BASE", "/tmp/workspace/users")
    user_workspace = os.path.join(workspace_base, uid)
    os.makedirs(user_workspace, exist_ok=True)

    options = ClaudeAgentOptions(
        model="claude-sonnet-4-6",
        permission_mode="bypassPermissions",
        cwd=user_workspace,
        system_prompt=build_system_prompt(mode),
        env={
            "HOME": "/home/appuser",
            # OAT トークンは ANTHROPIC_API_KEY ではなく CLAUDE_CODE_OAUTH_TOKEN で渡す
            "ANTHROPIC_API_KEY": "",
            "CLAUDE_CODE_OAUTH_TOKEN": os.getenv("ANTHROPIC_API_KEY", ""),
        },
        allowed_tools=[
            "Read", "Glob", "Grep",
            "mcp__google-search__*",
            "mcp__brave-search__*",
            "mcp__paper-search__*",
            "mcp__arxiv__*",
            "mcp__semantic-scholar__*",
            "mcp__estat__*",
            "mcp__e-gov-law__*",
            "mcp__fetch__*",
        ],
    )
    if session_id:
        options.resume = session_id

    _sentinel = object()
    queue: asyncio.Queue = asyncio.Queue()

    async def _producer() -> None:
        try:
            async for msg in query(prompt=message, options=options):
                await queue.put(msg)
        except Exception as exc:
            logger.exception("run_agent producer error: %s", exc)
            await queue.put(exc)
        finally:
            await queue.put(_sentinel)

    task = asyncio.create_task(_producer())

    try:
        while True:
            try:
                item = await asyncio.wait_for(
                    queue.get(), timeout=_INTER_MESSAGE_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Agent inter-message timeout (%ds) for uid=%s mode=%s",
                    _INTER_MESSAGE_TIMEOUT, uid, mode,
                )
                task.cancel()
                raise TimeoutError(
                    f"エージェントが{_INTER_MESSAGE_TIMEOUT}秒以上応答しませんでした。"
                    "再度お試しください。"
                )

            if item is _sentinel:
                break
            if isinstance(item, Exception):
                raise item
            yield item

    finally:
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
