"""`_run_async` sync ⇄ async ブリッジのテスト。

VertexGeminiClient が `llm-client` (async API) を内部で叩くため、
driving-license-bot 側の sync `generate()` から呼ぶ際の bridge ロジックを検証。

検証パス:
1. 走っている event loop が無い: `asyncio.run` 経路 (CLI バッチ想定)
2. 走っている event loop がある: 別 thread 経路 (FastAPI pipeline.run async
   から sync `generate()` 経由で呼ばれるケース)
3. coroutine が例外を raise したら呼出元に伝播する
"""

from __future__ import annotations

import asyncio

import pytest

from app.agent.llm_client import _run_async


def test_run_async_returns_value_when_no_loop_running() -> None:
    async def _coro() -> int:
        await asyncio.sleep(0)
        return 42

    assert _run_async(_coro()) == 42


def test_run_async_propagates_exception_when_no_loop_running() -> None:
    async def _coro() -> int:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        _run_async(_coro())


async def test_run_async_works_inside_running_loop() -> None:
    """async test 関数の中で _run_async を呼ぶ = 既存 loop が走っている状況。"""

    async def _coro() -> str:
        await asyncio.sleep(0)
        return "ok"

    # 直接 _run_async に渡す。 thread bridge 経由で実行されることを確認。
    assert _run_async(_coro()) == "ok"


async def test_run_async_inside_loop_propagates_exception() -> None:
    async def _coro() -> str:
        raise RuntimeError("inner-boom")

    with pytest.raises(RuntimeError, match="inner-boom"):
        _run_async(_coro())
