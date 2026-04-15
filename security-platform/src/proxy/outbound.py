"""Outbound Inspection for MCP Gateway.

Inspects MCP server responses BEFORE they are returned to the agent.
Implements checks 7-9 from the design spec:

  7. Response injection detection — prompt injection in MCP tool results (ASI01, ASI08)
  8. Response DLP scan           — sensitive data leaking back to agent (ASI06)
  9. Response size limit         — prevent memory-exhaustion attacks (ASI02)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from .dlp import DLPEngine
from .injection import InjectionDetector

logger = logging.getLogger(__name__)

# 10 MB default max response size
_DEFAULT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024


@dataclass
class OutboundVerdict:
    """Result of outbound inspection."""
    passed: bool
    block_reason: str | None    # e.g. "INJECTION_RESPONSE", "DLP_INBOUND", "RESPONSE_SIZE"
    block_detail: str | None    # Human-readable explanation


class OutboundInspector:
    """Performs all outbound (response-side) security checks for the MCP Gateway."""

    def __init__(
        self,
        injection_detector: InjectionDetector,
        dlp_engine: DLPEngine,
        max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
    ):
        self._injection = injection_detector
        self._dlp = dlp_engine
        self._max_response_bytes = max_response_bytes

    def inspect(
        self,
        response_body: str | bytes | dict[str, Any] | None,
        tool_name: str = "",
    ) -> OutboundVerdict:
        """Run all outbound checks on the MCP server response.

        Args:
            response_body: Raw response content (str, bytes, or parsed dict).
            tool_name: Tool name for logging context.

        Returns:
            OutboundVerdict with passed=True if all checks pass.
        """
        # Normalise to string for scanning
        if response_body is None:
            return OutboundVerdict(passed=True, block_reason=None, block_detail=None)

        if isinstance(response_body, bytes):
            raw_str = response_body.decode("utf-8", errors="replace")
        elif isinstance(response_body, dict):
            raw_str = json.dumps(response_body, default=str)
        else:
            raw_str = str(response_body)

        # --- Check 9: Response size limit (fast path first) ---
        byte_size = len(raw_str.encode("utf-8"))
        if byte_size > self._max_response_bytes:
            return OutboundVerdict(
                passed=False,
                block_reason="RESPONSE_SIZE",
                block_detail=(
                    f"Response from '{tool_name}' exceeds size limit "
                    f"({byte_size:,} bytes > {self._max_response_bytes:,} bytes). "
                    "Possible memory exhaustion attack."
                ),
            )

        # --- Check 7: Injection detection in response (all categories including prompt) ---
        # Outbound inspection scans for ALL injection types, especially prompt injection
        # that may be embedded in MCP tool results to hijack the agent's reasoning.
        injection_matches = self._injection.scan_text(raw_str)
        if injection_matches:
            first = injection_matches[0]
            logger.warning(
                "Injection pattern in MCP response [tool=%s]: %s at %s — '%s'",
                tool_name,
                first.pattern_name,
                first.field_path,
                first.matched_text[:80],
            )
            return OutboundVerdict(
                passed=False,
                block_reason="INJECTION_RESPONSE",
                block_detail=(
                    f"Injection pattern in MCP server response: "
                    f"{first.pattern_name} ({first.pattern_category}) — "
                    f"'{first.matched_text[:80]}'"
                ),
            )

        # --- Check 8: DLP scan on response content ---
        _, violations = self._dlp.scan_and_redact({"response": raw_str})
        if violations:
            summary = ", ".join(f"{v.pattern_name}" for v in violations)
            logger.warning("DLP violation in MCP response [tool=%s]: %s", tool_name, summary)
            return OutboundVerdict(
                passed=False,
                block_reason="DLP_INBOUND",
                block_detail=(
                    f"Sensitive data detected in MCP server response: {summary}. "
                    "Response blocked to prevent credential leakage to agent context."
                ),
            )

        return OutboundVerdict(passed=True, block_reason=None, block_detail=None)
