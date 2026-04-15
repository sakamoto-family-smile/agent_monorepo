"""Tests for CVSS-based severity scorer."""
from __future__ import annotations

import pytest
from src.analyzer.scorer import classify_severity, score_vulnerability


# ---------------------------------------------------------------------------
# classify_severity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("score,expected", [
    (9.5, "CRITICAL"),
    (9.0, "CRITICAL"),
    (8.9, "HIGH"),
    (7.0, "HIGH"),
    (6.9, "MEDIUM"),
    (4.0, "MEDIUM"),
    (3.9, "LOW"),
    (0.0, "LOW"),
    (None, "LOW"),
])
def test_classify_severity(score, expected):
    assert classify_severity(score) == expected


def test_kev_escalates_to_critical():
    """A CVSS 7.0 + in_kev=True should escalate to CRITICAL."""
    result = classify_severity(7.0, in_kev=True)
    assert result == "CRITICAL"


# ---------------------------------------------------------------------------
# score_vulnerability
# ---------------------------------------------------------------------------

def test_score_vulnerability_no_match():
    """No inventory match — severity stays at base CVSS classification."""
    vuln = {
        "cvss_score": 5.0,
        "title": "Some vulnerability",
        "description": "A medium severity vulnerability.",
        "tags": [],
        "owasp_asi": [],
    }
    result = score_vulnerability(vuln, inventory_match=False)
    assert result["severity"] == "MEDIUM"
    assert result["inventory_match"] is False


def test_score_vulnerability_inventory_match_upgrades():
    """Inventory match should bump severity one level (MEDIUM → HIGH)."""
    vuln = {
        "cvss_score": 5.0,
        "title": "Some vulnerability",
        "description": "A medium severity vulnerability.",
        "tags": [],
        "owasp_asi": [],
    }
    result = score_vulnerability(vuln, inventory_match=True)
    assert result["severity"] == "HIGH"
    assert result["inventory_match"] is True


def test_score_vulnerability_critical_not_bumped():
    """CRITICAL should not be bumped further even with inventory match."""
    vuln = {
        "cvss_score": 9.5,
        "title": "Critical vulnerability",
        "description": "Critical severity.",
        "tags": [],
        "owasp_asi": [],
    }
    result = score_vulnerability(vuln, inventory_match=True)
    assert result["severity"] == "CRITICAL"


# ---------------------------------------------------------------------------
# OWASP mapping
# ---------------------------------------------------------------------------

def test_owasp_mapping_mcp_rce():
    """Tags: mcp, rce → should map to ASI-related codes via description keywords."""
    vuln = {
        "cvss_score": 9.8,
        "title": "MCP Server RCE via Shell Injection",
        "description": "A shell injection vulnerability in the MCP server allows remote code execution.",
        "tags": ["mcp", "rce"],
        "owasp_asi": [],
    }
    result = score_vulnerability(vuln)
    owasp = result["owasp_asi"]
    # Shell injection maps to ASI02
    assert "ASI02" in owasp


def test_owasp_mapping_prompt_injection():
    """'prompt injection' in description → ASI01."""
    vuln = {
        "cvss_score": 7.5,
        "title": "Indirect prompt injection in LLM",
        "description": "Indirect prompt injection allows attackers to hijack LLM reasoning.",
        "tags": [],
        "owasp_asi": [],
    }
    result = score_vulnerability(vuln)
    assert "ASI01" in result["owasp_asi"]


def test_owasp_mapping_sql_injection():
    """'sql injection' in description → ASI02."""
    vuln = {
        "cvss_score": 8.0,
        "title": "SQL Injection in MCP Data Tool",
        "description": "SQL injection vulnerability allows database manipulation.",
        "tags": [],
        "owasp_asi": [],
    }
    result = score_vulnerability(vuln)
    assert "ASI02" in result["owasp_asi"]
