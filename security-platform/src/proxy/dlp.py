"""Data Loss Prevention - scan tool parameters for sensitive data."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

SCAN_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "scan.yaml"

DEFAULT_PATTERNS = [
    {
        "name": "API_KEY",
        "pattern": r'(?i)(api[_-]?key|apikey)\s*[:=]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?',
    },
    {
        "name": "AWS_SECRET",
        "pattern": r'(?i)aws[_-]?secret[_-]?access[_-]?key\s*[:=]\s*["\']?([a-zA-Z0-9/+]{40})["\']?',
    },
    {
        "name": "CREDIT_CARD",
        "pattern": r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b',
    },
    {
        "name": "PRIVATE_KEY",
        "pattern": r'-----BEGIN (?:RSA |EC )?PRIVATE KEY-----',
    },
    {
        "name": "JWT_TOKEN",
        "pattern": r'eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}',
    },
]


@dataclass
class DLPViolation:
    """Represents a DLP violation found in tool parameters."""
    pattern_name: str
    field_path: str
    masked_value: str
    original_length: int


def _load_patterns() -> list[dict[str, str]]:
    """Load DLP patterns from scan.yaml, falling back to defaults."""
    if not SCAN_CONFIG_PATH.exists():
        return DEFAULT_PATTERNS
    try:
        with open(SCAN_CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("proxy", {}).get("dlp", {}).get("patterns", DEFAULT_PATTERNS)
    except Exception as exc:
        logger.warning("Failed to load DLP patterns from config: %s", exc)
        return DEFAULT_PATTERNS


def _mask_value(value: str) -> str:
    """Mask a sensitive value, keeping first and last 4 characters."""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


class DLPEngine:
    """Scans data structures for sensitive information patterns."""

    def __init__(self) -> None:
        raw_patterns = _load_patterns()
        self._compiled: list[tuple[str, re.Pattern]] = []
        for p in raw_patterns:
            try:
                compiled = re.compile(p["pattern"], re.IGNORECASE | re.MULTILINE)
                self._compiled.append((p["name"], compiled))
            except re.error as exc:
                logger.warning("Invalid DLP pattern '%s': %s", p["name"], exc)

    def scan(self, data: dict[str, Any]) -> list[DLPViolation]:
        """Scan a data dict (e.g., tool parameters) for sensitive data patterns.

        Returns a list of DLPViolation objects.
        """
        violations: list[DLPViolation] = []
        self._scan_recursive(data, "", violations)
        return violations

    def _scan_recursive(
        self,
        obj: Any,
        path: str,
        violations: list[DLPViolation],
    ) -> None:
        """Recursively scan nested data structures."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                child_path = f"{path}.{key}" if path else key
                self._scan_recursive(value, child_path, violations)
        elif isinstance(obj, (list, tuple)):
            for i, item in enumerate(obj):
                self._scan_recursive(item, f"{path}[{i}]", violations)
        elif isinstance(obj, str):
            self._scan_string(obj, path, violations)
        elif obj is not None:
            # Convert non-string scalars to string for scanning
            self._scan_string(str(obj), path, violations)

    def _scan_string(
        self,
        value: str,
        path: str,
        violations: list[DLPViolation],
    ) -> None:
        """Scan a string value against all DLP patterns."""
        for pattern_name, pattern in self._compiled:
            matches = pattern.findall(value)
            if matches:
                # Get the matched string
                match_obj = pattern.search(value)
                if match_obj:
                    matched_str = match_obj.group(0)
                    violations.append(DLPViolation(
                        pattern_name=pattern_name,
                        field_path=path,
                        masked_value=_mask_value(matched_str),
                        original_length=len(matched_str),
                    ))

    def scan_and_redact(
        self,
        data: dict[str, Any],
    ) -> tuple[dict[str, Any], list[DLPViolation]]:
        """Scan data and return a redacted copy along with violations.

        The returned dict has sensitive values replaced with masked versions.
        """
        violations = self.scan(data)
        if not violations:
            return data, []

        # Deep copy and redact
        redacted = json.loads(json.dumps(data, default=str))
        for violation in violations:
            self._redact_at_path(redacted, violation.field_path, violation.masked_value)

        return redacted, violations

    def _redact_at_path(self, obj: Any, path: str, replacement: str) -> None:
        """Redact a value at the given dot-notation path."""
        parts = path.replace("[", ".[").split(".")
        target = obj
        for i, part in enumerate(parts[:-1]):
            if part.startswith("["):
                idx = int(part[1:-1])
                target = target[idx]
            elif part in target:
                target = target[part]
            else:
                return

        last = parts[-1]
        try:
            if last.startswith("["):
                idx = int(last[1:-1])
                target[idx] = replacement
            elif isinstance(target, dict) and last in target:
                target[last] = replacement
        except (KeyError, IndexError, TypeError):
            pass
