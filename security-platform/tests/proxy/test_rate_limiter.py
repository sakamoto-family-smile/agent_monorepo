"""Tests for RateLimiter."""
from __future__ import annotations

import pytest
from src.proxy.rate_limiter import RateLimiter


@pytest.mark.anyio
async def test_allows_under_limit():
    limiter = RateLimiter(max_calls_per_minute=100)
    result = await limiter.allow("test_tool")
    assert result is True


@pytest.mark.anyio
async def test_blocks_over_limit():
    """When max_calls_per_minute=1 and per-tool-limit is 1, second call is blocked."""
    # max_calls_per_minute=5 means per_tool_limit = max(5, 5//5) = max(5,1) = 5
    # We use max_calls_per_minute=1 so per_tool_limit = max(5, 0) = 5 but global=1
    # To reliably trigger blocking, set a very small limit and exhaust it
    limiter = RateLimiter(max_calls_per_minute=1)
    # First call should succeed (global counter = 1 = limit → next call fails)
    first = await limiter.allow("tool_a")
    assert first is True
    # Second call should be blocked by global rate limit
    second = await limiter.allow("tool_a")
    assert second is False


@pytest.mark.anyio
async def test_circuit_breaker_opens_after_failures():
    limiter = RateLimiter(
        max_calls_per_minute=1000,
        circuit_breaker_threshold=3,
    )
    tool = "flaky_tool"
    # Record enough failures to open the circuit breaker
    for _ in range(3):
        await limiter.record_failure(tool)

    # Now the circuit should be open and the call should be blocked
    allowed = await limiter.allow(tool)
    assert allowed is False


@pytest.mark.anyio
async def test_get_stats_returns_dict():
    limiter = RateLimiter(max_calls_per_minute=100)
    await limiter.allow("some_tool")
    stats = await limiter.get_stats()
    assert isinstance(stats, dict)
    assert "some_tool" in stats
    assert "calls_last_minute" in stats["some_tool"]
    assert "circuit_open" in stats["some_tool"]
