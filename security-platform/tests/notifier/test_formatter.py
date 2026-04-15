"""Tests for notification formatter."""
from __future__ import annotations

from unittest.mock import MagicMock
from datetime import datetime, timezone

import pytest


def _make_vuln(
    cve_id="CVE-2024-1234",
    severity="CRITICAL",
    cvss_score=9.8,
    title="MCP Server RCE Vulnerability",
    description="Path traversal vulnerability in MCP filesystem server allows arbitrary file read.",
    source="nvd",
    affected_component_name="@modelcontextprotocol/server-filesystem",
    affected_component_version="< 0.6.0",
    inventory_match=True,
    matched_components=None,
    owasp_asi=None,
    recommended_actions=None,
    ghsa_id=None,
):
    """Create a mock Vulnerability object with the given attributes."""
    vuln = MagicMock()
    vuln.cve_id = cve_id
    vuln.ghsa_id = ghsa_id
    vuln.severity = severity
    vuln.cvss_score = cvss_score
    vuln.title = title
    vuln.description = description
    vuln.source = source
    vuln.affected_component_name = affected_component_name
    vuln.affected_component_version = affected_component_version
    vuln.inventory_match = inventory_match
    vuln.matched_components = matched_components or ["agent-system-1"]
    vuln.owasp_asi = owasp_asi or ["ASI02", "AST05"]
    vuln.recommended_actions = recommended_actions
    return vuln


# ---------------------------------------------------------------------------
# format_immediate
# ---------------------------------------------------------------------------

def test_format_immediate_critical():
    from src.notifier.formatter import format_immediate

    vuln = _make_vuln(severity="CRITICAL", cvss_score=9.8)
    output = format_immediate(vuln)

    assert "CVE-2024-1234" in output
    assert "CRITICAL" in output
    assert "9.8" in output
    # CRITICAL emoji
    assert "🚨" in output


def test_format_immediate_high():
    from src.notifier.formatter import format_immediate

    vuln = _make_vuln(severity="HIGH", cvss_score=8.1)
    output = format_immediate(vuln)

    assert "HIGH" in output
    assert "8.1" in output
    assert "🔴" in output


def test_format_immediate_inventory_match_shown():
    from src.notifier.formatter import format_immediate

    vuln = _make_vuln(inventory_match=True, matched_components=["agent-system-1"])
    output = format_immediate(vuln)
    assert "YES" in output
    assert "agent-system-1" in output


def test_format_immediate_no_inventory_match():
    from src.notifier.formatter import format_immediate

    vuln = _make_vuln(inventory_match=False, matched_components=[])
    output = format_immediate(vuln)
    assert "No" in output


# ---------------------------------------------------------------------------
# format_digest
# ---------------------------------------------------------------------------

def test_format_digest_groups_by_severity():
    from src.notifier.formatter import format_digest

    vulns = [
        _make_vuln(cve_id="CVE-2024-0001", severity="CRITICAL"),
        _make_vuln(cve_id="CVE-2024-0002", severity="HIGH"),
        _make_vuln(cve_id="CVE-2024-0003", severity="HIGH"),
        _make_vuln(cve_id="CVE-2024-0004", severity="MEDIUM"),
    ]
    output = format_digest(vulns)

    assert "CRITICAL" in output
    assert "HIGH" in output
    assert "MEDIUM" in output
    # Summary counts
    assert "CRITICAL: 1" in output
    assert "HIGH:     2" in output
    assert "MEDIUM:   1" in output
    assert "TOTAL:    4" in output


def test_format_digest_empty():
    from src.notifier.formatter import format_digest

    output = format_digest([])
    assert "No new vulnerabilities" in output
