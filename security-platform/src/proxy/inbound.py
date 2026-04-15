"""Inbound Inspection for MCP Gateway.

Inspects MCP tool call requests BEFORE they are forwarded to external MCP servers.
Implements checks 1-6 from the design spec:

  1. Rate limiting          — prevents infinite loops / DoS (ASI02)
  2. Tool definition hash   — detects Rug Pull (ASI04, AST01)
  3. Injection detection    — command + SQL patterns (ASI01, ASI02)
  4. DLP scan               — sensitive data in outbound request (ASI06)
  5. Destination allowlist  — unauthorized external endpoints (ASI04)
  6. Cost limit check       — hourly API cost ceiling (ASI02)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from .destination import DestinationChecker
from .dlp import DLPEngine
from .injection import InjectionDetector
from .rate_limiter import RateLimiter
from .tool_pinning import ToolPinStore

logger = logging.getLogger(__name__)


@dataclass
class InboundVerdict:
    """Result of inbound inspection."""
    passed: bool
    block_reason: str | None        # e.g. "RATE_LIMIT", "INJECTION", etc.
    block_detail: str | None        # Human-readable explanation
    description_hash: str | None    # Computed tool description hash (for audit log)


class InboundInspector:
    """Performs all inbound (request-side) security checks for the MCP Gateway."""

    def __init__(
        self,
        rate_limiter: RateLimiter,
        tool_pin_store: ToolPinStore,
        injection_detector: InjectionDetector,
        dlp_engine: DLPEngine,
        destination_checker: DestinationChecker,
        max_usd_per_hour: float = 10.0,
    ):
        self._rate_limiter = rate_limiter
        self._tool_pins = tool_pin_store
        self._injection = injection_detector
        self._dlp = dlp_engine
        self._dest = destination_checker
        self._max_usd_per_hour = max_usd_per_hour
        self._hourly_cost: float = 0.0  # Simple in-memory accumulator

    async def inspect(
        self,
        tool_name: str,
        tool_description: str,
        parameters: dict[str, Any],
        destination_url: str,
        estimated_cost_usd: float = 0.0,
    ) -> InboundVerdict:
        """Run all inbound checks. Returns the first failing check or PASS.

        Args:
            tool_name: MCP tool identifier.
            tool_description: Tool description string (for rug-pull detection).
            parameters: Tool call parameters dict.
            destination_url: Target MCP server URL.
            estimated_cost_usd: Estimated API cost for this call.
        """
        import hashlib

        # --- Check 1: Rate limiting ---
        if not await self._rate_limiter.allow(tool_name):
            return InboundVerdict(
                passed=False,
                block_reason="RATE_LIMIT",
                block_detail=f"Tool '{tool_name}' exceeded rate limit or circuit breaker is open",
                description_hash=None,
            )

        # --- Check 2: Tool definition integrity (Rug Pull detection) ---
        description_hash: str | None = None
        if tool_description:
            description_hash = hashlib.sha256(tool_description.encode()).hexdigest()
            is_valid = await self._tool_pins.verify(tool_name, description_hash)
            if not is_valid:
                return InboundVerdict(
                    passed=False,
                    block_reason="TOOL_INTEGRITY",
                    block_detail=(
                        f"Tool '{tool_name}' description hash changed "
                        f"(current={description_hash[:12]}…). Possible Rug Pull attack."
                    ),
                    description_hash=description_hash,
                )
            # Register on first call (verify returns True for new tools)
            await self._tool_pins.register(tool_name, tool_description)

        # --- Check 3: Injection detection (command + SQL only for inbound) ---
        injection_matches = self._injection.scan(
            parameters,
            categories={"command", "sql"},
        )
        if injection_matches:
            first = injection_matches[0]
            return InboundVerdict(
                passed=False,
                block_reason="INJECTION",
                block_detail=(
                    f"Injection pattern detected in request: "
                    f"{first.pattern_name} at {first.field_path}"
                ),
                description_hash=description_hash,
            )

        # --- Check 4: DLP scan on outbound parameters ---
        _, violations = self._dlp.scan_and_redact(parameters)
        if violations:
            summary = ", ".join(f"{v.pattern_name} at {v.field_path}" for v in violations)
            return InboundVerdict(
                passed=False,
                block_reason="DLP_OUTBOUND",
                block_detail=f"Sensitive data detected in request parameters: {summary}",
                description_hash=description_hash,
            )

        # --- Check 5: Destination allowlist ---
        if not self._dest.is_allowed(destination_url):
            return InboundVerdict(
                passed=False,
                block_reason="DESTINATION",
                block_detail=f"Destination not in allowlist: {destination_url}",
                description_hash=description_hash,
            )

        # --- Check 6: Cost limit ---
        if self._hourly_cost + estimated_cost_usd > self._max_usd_per_hour:
            return InboundVerdict(
                passed=False,
                block_reason="COST_LIMIT",
                block_detail=(
                    f"Hourly cost limit ${self._max_usd_per_hour:.2f} would be exceeded. "
                    f"Current: ${self._hourly_cost:.4f}, Request: ${estimated_cost_usd:.4f}"
                ),
                description_hash=description_hash,
            )
        self._hourly_cost += estimated_cost_usd

        return InboundVerdict(
            passed=True,
            block_reason=None,
            block_detail=None,
            description_hash=description_hash,
        )

    def reset_hourly_cost(self) -> None:
        """Reset the hourly cost accumulator (call this every hour)."""
        self._hourly_cost = 0.0
