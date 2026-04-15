"""Tests for DestinationChecker."""
from __future__ import annotations

import pytest
from src.proxy.destination import DestinationChecker


# ---------------------------------------------------------------------------
# Default allowlist — localhost variants
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "http://localhost:9000/tool",
    "http://127.0.0.1:8080",
])
def test_localhost_allowed_by_default(url):
    checker = DestinationChecker()
    assert checker.is_allowed(url) is True


# ---------------------------------------------------------------------------
# Wildcard support
# ---------------------------------------------------------------------------

def test_wildcard_subdomain_allowed():
    checker = DestinationChecker(allowed_destinations=["*.example.com"])
    assert checker.is_allowed("https://api.example.com/mcp") is True


def test_wildcard_root_domain_also_allowed():
    """The root domain itself (example.com) should be allowed when *.example.com is in the list."""
    checker = DestinationChecker(allowed_destinations=["*.example.com"])
    assert checker.is_allowed("https://example.com/mcp") is True


# ---------------------------------------------------------------------------
# Blocked scenarios
# ---------------------------------------------------------------------------

def test_unlisted_domain_blocked():
    checker = DestinationChecker()  # defaults to localhost only
    assert checker.is_allowed("https://evil.com/exfiltrate") is False


def test_malformed_url_blocked():
    checker = DestinationChecker()
    # A completely non-URL string without a valid host
    assert checker.is_allowed("not-a-url") is False


def test_empty_url_blocked():
    checker = DestinationChecker()
    assert checker.is_allowed("") is False


# ---------------------------------------------------------------------------
# Custom allowlist
# ---------------------------------------------------------------------------

def test_custom_allowlist():
    checker = DestinationChecker(allowed_destinations=["api.mycompany.com"])
    assert checker.is_allowed("https://api.mycompany.com/tools/search") is True
    assert checker.is_allowed("https://other.com/tools") is False
