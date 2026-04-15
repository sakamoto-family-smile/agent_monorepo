"""Injection detection engine for MCP Gateway.

Detects command injection, SQL injection, and prompt injection patterns
in both inbound requests (tool parameters) and outbound responses (MCP tool results).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class InjectionMatch:
    """A detected injection pattern."""
    pattern_name: str
    pattern_category: str  # "command" | "sql" | "prompt"
    matched_text: str      # The matched portion (truncated for logging)
    field_path: str        # Where in the payload it was found


# Default injection pattern set aligned with OWASP ASI01/ASI02 and Layer 3 design
_DEFAULT_PATTERNS: list[dict[str, str]] = [
    # --- Command injection (ASI02, AST05) ---
    {
        "name": "SHELL_COMMAND_CHAINING",
        "category": "command",
        "pattern": r";\s*(rm|cat|curl|wget|nc|bash|sh|python|node|perl|ruby)\s",
    },
    {
        "name": "SHELL_SUBSHELL",
        "category": "command",
        "pattern": r"\$\([^)]{1,200}\)",
    },
    {
        "name": "SHELL_BACKTICK",
        "category": "command",
        "pattern": r"`[^`]{1,200}`",
    },
    {
        "name": "PATH_TRAVERSAL",
        "category": "command",
        "pattern": r"\.\./\.\./|\.\.\\\.\.\\",
    },
    {
        "name": "PYTHON_EXEC",
        "category": "command",
        "pattern": r"__import__\s*\(\s*['\"]os['\"]",
    },
    # --- SQL injection (ASI02) ---
    {
        "name": "SQL_OR_BYPASS",
        "category": "sql",
        "pattern": r"'\s*(OR|AND)\s+['\"]?\d+['\"]?\s*=\s*['\"]?\d+",
    },
    {
        "name": "SQL_COMMENT_BYPASS",
        "category": "sql",
        "pattern": r"--\s*$|/\*.*\*/",
    },
    {
        "name": "SQL_STACKED_QUERY",
        "category": "sql",
        "pattern": r";\s*(DROP|DELETE|UPDATE|INSERT|CREATE|ALTER|TRUNCATE)\s",
    },
    {
        "name": "SQL_UNION",
        "category": "sql",
        "pattern": r"\bUNION\s+(ALL\s+)?SELECT\b",
    },
    # --- Prompt injection (ASI01, ASI08) - used primarily for Outbound (response) inspection ---
    {
        "name": "PROMPT_IGNORE_INSTRUCTIONS",
        "category": "prompt",
        "pattern": r"(?i)(ignore|disregard|forget)\s+(all\s+)?(previous|above|prior)\s+(instructions?|rules?|prompts?|directives?)",
    },
    {
        "name": "PROMPT_SYSTEM_OVERRIDE",
        "category": "prompt",
        "pattern": r"(?i)system\s*:\s*you\s+are\s+now",
    },
    {
        "name": "PROMPT_NEW_INSTRUCTIONS",
        "category": "prompt",
        "pattern": r"(?i)\[\s*(new|updated|revised)\s+instructions?\s*\]",
    },
    {
        "name": "PROMPT_ROLE_SWITCH",
        "category": "prompt",
        "pattern": r"(?i)(you\s+are\s+now|act\s+as|pretend\s+(to\s+be|you\s+are))\s+.{0,50}(assistant|ai|bot|model|gpt|claude)",
    },
    {
        "name": "PROMPT_DAN_JAILBREAK",
        "category": "prompt",
        "pattern": r"(?i)\b(DAN|jailbreak|do\s+anything\s+now|developer\s+mode)\b",
    },
    {
        "name": "PROMPT_HIDDEN_COMMAND",
        "category": "prompt",
        "pattern": r"(?i)<\s*(hidden|secret|covert|invisible)\s*>(.*?)<\s*/\s*(hidden|secret|covert|invisible)\s*>",
    },
]

# Compiled pattern cache
_compiled: list[tuple[str, str, re.Pattern[str]]] | None = None


def _get_compiled_patterns(extra_patterns: list[dict[str, str]] | None = None) -> list[tuple[str, str, re.Pattern[str]]]:
    """Return compiled regex patterns (cached for defaults, fresh for extras)."""
    global _compiled
    if _compiled is None:
        _compiled = [
            (p["name"], p["category"], re.compile(p["pattern"], re.IGNORECASE | re.MULTILINE))
            for p in _DEFAULT_PATTERNS
        ]
    if not extra_patterns:
        return _compiled
    extra = [
        (p["name"], p["category"], re.compile(p["pattern"], re.IGNORECASE | re.MULTILINE))
        for p in extra_patterns
    ]
    return _compiled + extra


def _scan_text(text: str, compiled: list[tuple[str, str, re.Pattern[str]]], field_path: str) -> list[InjectionMatch]:
    """Scan a string against all patterns."""
    matches = []
    for name, category, pattern in compiled:
        m = pattern.search(text)
        if m:
            matched = m.group(0)[:100]  # Truncate for safe logging
            matches.append(InjectionMatch(
                pattern_name=name,
                pattern_category=category,
                matched_text=matched,
                field_path=field_path,
            ))
    return matches


def _scan_value(value: Any, compiled: list[tuple[str, str, re.Pattern[str]]], path: str) -> list[InjectionMatch]:
    """Recursively scan a value (str, dict, list) for injection patterns."""
    if isinstance(value, str):
        return _scan_text(value, compiled, path)
    if isinstance(value, dict):
        results = []
        for k, v in value.items():
            results.extend(_scan_value(v, compiled, f"{path}.{k}"))
        return results
    if isinstance(value, list):
        results = []
        for i, item in enumerate(value):
            results.extend(_scan_value(item, compiled, f"{path}[{i}]"))
        return results
    return []


class InjectionDetector:
    """Detects injection patterns in MCP tool call parameters and responses.

    Used by both InboundInspector (request parameters) and OutboundInspector
    (MCP server responses), with different category filters applied:
    - Inbound: command + SQL injection (user-controlled input going out)
    - Outbound: all categories including prompt injection (response coming back to agent)
    """

    def __init__(self, extra_patterns: list[dict[str, str]] | None = None):
        self._extra = extra_patterns
        self._patterns = _get_compiled_patterns(extra_patterns)

    def scan(
        self,
        data: Any,
        *,
        categories: set[str] | None = None,
    ) -> list[InjectionMatch]:
        """Scan data for injection patterns.

        Args:
            data: Arbitrary payload (str, dict, list) to inspect.
            categories: If provided, only check patterns in these categories.
                        e.g. {"command", "sql"} for inbound, None for all.

        Returns:
            List of InjectionMatch findings (empty = clean).
        """
        patterns = self._patterns
        if categories is not None:
            patterns = [(n, c, p) for n, c, p in patterns if c in categories]
        return _scan_value(data, patterns, "root")

    def scan_text(self, text: str, *, categories: set[str] | None = None) -> list[InjectionMatch]:
        """Convenience method to scan a plain string."""
        patterns = self._patterns
        if categories is not None:
            patterns = [(n, c, p) for n, c, p in patterns if c in categories]
        return _scan_text(text, patterns, "text")
