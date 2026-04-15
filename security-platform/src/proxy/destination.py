"""Destination allowlist checker for MCP Gateway.

Verifies that the target MCP server URL/domain is in the configured
allowlist before forwarding requests. Prevents data exfiltration to
unauthorized external endpoints (OWASP ASI04).
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Default allowlist: localhost for development.
# Production should explicitly list approved MCP server domains.
_DEFAULT_ALLOWED: list[str] = [
    "localhost",
    "127.0.0.1",
    "::1",
]


class DestinationChecker:
    """Checks whether a target URL/domain is in the configured allowlist."""

    def __init__(self, allowed_destinations: list[str] | None = None):
        """
        Args:
            allowed_destinations: List of allowed hostnames or full URL prefixes.
                                  Supports:
                                  - Hostname only: "api.example.com"
                                  - URL prefix: "https://api.example.com/mcp"
                                  - Wildcard subdomain: "*.example.com"
                                  If None or empty, uses localhost-only defaults.
        """
        raw = allowed_destinations or _DEFAULT_ALLOWED
        self._entries = [e.strip() for e in raw if e.strip()]
        logger.debug("DestinationChecker initialized with %d entries", len(self._entries))

    def is_allowed(self, url: str) -> bool:
        """Return True if the URL's host is in the allowlist.

        Args:
            url: Full URL of the target MCP server endpoint.

        Returns:
            True if allowed, False if not.
        """
        try:
            parsed = urlparse(url)
            host = parsed.hostname or ""
        except Exception:
            logger.warning("Failed to parse destination URL: %s", url)
            return False

        if not host:
            return False

        for entry in self._entries:
            if self._matches(host, entry):
                return True

        logger.warning("Destination not in allowlist: %s (host=%s)", url, host)
        return False

    def _matches(self, host: str, entry: str) -> bool:
        """Check if host matches an allowlist entry."""
        # Strip any protocol prefix from the entry
        if "://" in entry:
            try:
                entry_host = urlparse(entry).hostname or ""
            except Exception:
                return False
        else:
            entry_host = entry.split("/")[0]  # Strip any path

        # Wildcard subdomain: "*.example.com"
        if entry_host.startswith("*."):
            suffix = entry_host[1:]  # ".example.com"
            return host == suffix[1:] or host.endswith(suffix)

        return host == entry_host
