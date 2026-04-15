"""Token bucket rate limiter for MCP tool calls."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEFAULT_MAX_CALLS_PER_MINUTE = 100
DEFAULT_CIRCUIT_BREAKER_THRESHOLD = 10


@dataclass
class _ToolState:
    """Per-tool rate limit and circuit breaker state."""
    call_times: deque[float] = field(default_factory=deque)
    consecutive_failures: int = 0
    circuit_open: bool = False
    circuit_opened_at: float = 0.0


class RateLimiter:
    """Sliding-window rate limiter with per-tool circuit breaker.

    Thread-safe via asyncio.Lock.
    """

    def __init__(
        self,
        max_calls_per_minute: int = DEFAULT_MAX_CALLS_PER_MINUTE,
        circuit_breaker_threshold: int = DEFAULT_CIRCUIT_BREAKER_THRESHOLD,
        circuit_reset_seconds: float = 60.0,
    ) -> None:
        self.max_calls_per_minute = max_calls_per_minute
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.circuit_reset_seconds = circuit_reset_seconds
        self._global_state = _ToolState()
        self._tool_states: dict[str, _ToolState] = {}
        self._lock = asyncio.Lock()

    def _get_state(self, tool_name: str) -> _ToolState:
        if tool_name not in self._tool_states:
            self._tool_states[tool_name] = _ToolState()
        return self._tool_states[tool_name]

    async def allow(self, tool_name: str) -> bool:
        """Check if a tool call is allowed under rate limits.

        Returns True if allowed, False if rate limited or circuit open.
        """
        async with self._lock:
            now = time.monotonic()
            state = self._get_state(tool_name)

            # Check circuit breaker - auto-reset after timeout
            if state.circuit_open:
                elapsed = now - state.circuit_opened_at
                if elapsed >= self.circuit_reset_seconds:
                    logger.info("Circuit breaker reset for tool '%s'", tool_name)
                    state.circuit_open = False
                    state.consecutive_failures = 0
                else:
                    logger.warning(
                        "Circuit open for tool '%s' (%.0fs remaining)",
                        tool_name,
                        self.circuit_reset_seconds - elapsed,
                    )
                    return False

            # Sliding window: remove calls older than 60s
            cutoff = now - 60.0
            while state.call_times and state.call_times[0] < cutoff:
                state.call_times.popleft()

            # Check global rate (all tools combined)
            while self._global_state.call_times and self._global_state.call_times[0] < cutoff:
                self._global_state.call_times.popleft()

            if len(self._global_state.call_times) >= self.max_calls_per_minute:
                logger.warning("Global rate limit exceeded (%d calls/min)", self.max_calls_per_minute)
                return False

            # Per-tool rate: max 20 calls/minute per tool
            per_tool_limit = max(5, self.max_calls_per_minute // 5)
            if len(state.call_times) >= per_tool_limit:
                logger.warning("Per-tool rate limit exceeded for '%s'", tool_name)
                return False

            state.call_times.append(now)
            self._global_state.call_times.append(now)
            return True

    async def record_success(self, tool_name: str) -> None:
        """Record a successful tool call, resetting failure counter."""
        async with self._lock:
            state = self._get_state(tool_name)
            state.consecutive_failures = 0

    async def record_failure(self, tool_name: str) -> None:
        """Record a failed tool call, potentially opening the circuit breaker."""
        async with self._lock:
            state = self._get_state(tool_name)
            state.consecutive_failures += 1
            if state.consecutive_failures >= self.circuit_breaker_threshold:
                if not state.circuit_open:
                    logger.error(
                        "Circuit breaker OPENED for tool '%s' after %d consecutive failures",
                        tool_name,
                        state.consecutive_failures,
                    )
                    state.circuit_open = True
                    state.circuit_opened_at = time.monotonic()

    async def get_stats(self) -> dict[str, dict]:
        """Return current rate limiter statistics."""
        async with self._lock:
            now = time.monotonic()
            stats: dict[str, dict] = {}
            for tool_name, state in self._tool_states.items():
                cutoff = now - 60.0
                recent = sum(1 for t in state.call_times if t >= cutoff)
                stats[tool_name] = {
                    "calls_last_minute": recent,
                    "consecutive_failures": state.consecutive_failures,
                    "circuit_open": state.circuit_open,
                }
            return stats
