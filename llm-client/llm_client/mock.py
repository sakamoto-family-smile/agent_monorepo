"""オフライン/テスト用の決定論モック。"""

from __future__ import annotations

from .types import ChatMessage


class MockLLMClient:
    """オフライン/テスト用の決定論モック。

    fixed_reply を渡せば常にそれを返す。省略時は入力の先頭を引用した
    プレースホルダ文を返す。`cache_system` は受け取るが挙動には影響しない。
    """

    def __init__(self, fixed_reply: str | None = None) -> None:
        self._fixed = fixed_reply

    async def complete(
        self,
        *,
        system: str,
        user: str,
        cache_system: bool = False,
    ) -> str:
        if self._fixed is not None:
            return self._fixed
        preview = user.strip().splitlines()[0] if user.strip() else ""
        return (
            "【モック要約】入力の先頭を確認しました: "
            f"{preview[:80]}\n"
            "この応答はモックであり、実際の LLM 出力ではありません。"
        )

    async def complete_messages(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        cache_system: bool = False,
    ) -> str:
        if self._fixed is not None:
            return self._fixed
        last_user = ""
        for m in reversed(messages):
            if m["role"] == "user":
                last_user = m["content"]
                break
        preview = last_user.strip().splitlines()[0] if last_user.strip() else ""
        return (
            "【モック応答】最後のユーザー発話を確認しました: "
            f"{preview[:80]}\n"
            f"(履歴 {len(messages)} 件)\n"
            "この応答はモックであり、実際の LLM 出力ではありません。"
        )
