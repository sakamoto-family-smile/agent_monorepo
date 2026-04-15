"""CVSS-based severity scoring and classification."""
from __future__ import annotations

from typing import Any

# CVSS thresholds
CRITICAL_THRESHOLD = 9.0
HIGH_THRESHOLD = 7.0
MEDIUM_THRESHOLD = 4.0

# OWASP ASI mapping based on CWE/keyword patterns
OWASP_ASI_MAP: dict[str, list[str]] = {
    "prompt injection": ["ASI01", "AST10"],
    "indirect prompt injection": ["ASI01", "AST10"],
    "excessive agency": ["ASI01", "ASI02"],
    "privilege escalation": ["ASI03"],
    "access control": ["ASI03"],
    "authorization": ["ASI03"],
    "rbac": ["ASI03"],
    "supply chain": ["ASI04"],
    "dependency": ["ASI04"],
    "hijacking": ["ASI05"],
    "session": ["ASI05"],
    "pii": ["ASI06"],
    "personal data": ["ASI06"],
    "privacy": ["ASI06"],
    "misinformation": ["ASI07"],
    "hallucination": ["ASI07"],
    "plugin": ["ASI08"],
    "overly permissive": ["ASI08"],
    "training data": ["ASI09"],
    "model theft": ["ASI10"],
    "rug pull": ["ASI01", "ASI02"],
    "tool integrity": ["ASI01"],
    "path traversal": ["ASI02", "AST05"],
    "code injection": ["ASI02"],
    "shell injection": ["ASI02", "AST05"],
    "sql injection": ["ASI02"],
    "data exfiltration": ["ASI06"],
    "token exposure": ["ASI06"],
    "CWE-22": ["ASI02"],
    "CWE-78": ["ASI02"],
    "CWE-89": ["ASI02"],
    "CWE-94": ["ASI02"],
    "CWE-200": ["ASI06"],
    "CWE-312": ["ASI06"],
    "CWE-502": ["ASI04"],
    "CWE-601": ["ASI05"],
}


def classify_severity(
    cvss_score: float | None,
    in_kev: bool = False,
) -> str:
    """Classify severity based on CVSS score.

    Args:
        cvss_score: CVSS base score (0.0 - 10.0), or None
        in_kev: Whether this CVE is in the CISA Known Exploited Vulnerabilities catalog

    Returns:
        "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    """
    if cvss_score is None:
        return "LOW"

    if in_kev or cvss_score >= CRITICAL_THRESHOLD:
        return "CRITICAL"
    if cvss_score >= HIGH_THRESHOLD:
        return "HIGH"
    if cvss_score >= MEDIUM_THRESHOLD:
        return "MEDIUM"
    return "LOW"


def _severity_rank(severity: str) -> int:
    """Return numeric rank for severity comparison."""
    ranks = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    return ranks.get(severity.upper(), 1)


def _bump_severity(severity: str) -> str:
    """Bump severity up one level."""
    bumps = {"LOW": "MEDIUM", "MEDIUM": "HIGH", "HIGH": "CRITICAL", "CRITICAL": "CRITICAL"}
    return bumps.get(severity.upper(), severity)


def score_vulnerability(
    vuln_dict: dict[str, Any],
    inventory_match: bool = False,
) -> dict[str, Any]:
    """Enhance vulnerability scoring considering inventory match and other factors.

    Args:
        vuln_dict: Normalized vulnerability dict
        inventory_match: Whether this vuln affects a component in our inventory

    Returns:
        Updated vulnerability dict with enhanced severity and OWASP ASI tags
    """
    result = dict(vuln_dict)

    cvss_score = vuln_dict.get("cvss_score")
    base_severity = classify_severity(cvss_score)

    # Bump severity if inventory match
    effective_severity = base_severity
    if inventory_match and effective_severity != "CRITICAL":
        effective_severity = _bump_severity(effective_severity)

    result["severity"] = effective_severity
    result["inventory_match"] = inventory_match

    # Map OWASP ASI categories
    owasp_tags = list(vuln_dict.get("owasp_asi") or [])
    search_text = " ".join([
        vuln_dict.get("title", ""),
        vuln_dict.get("description", ""),
        " ".join(vuln_dict.get("tags", []) or []),
    ]).lower()

    for keyword, asi_codes in OWASP_ASI_MAP.items():
        if keyword.lower() in search_text:
            for code in asi_codes:
                if code not in owasp_tags:
                    owasp_tags.append(code)

    result["owasp_asi"] = owasp_tags
    return result


def severity_badge_color(severity: str) -> str:
    """Return a hex color for severity badges in the dashboard."""
    colors = {
        "CRITICAL": "#dc2626",
        "HIGH": "#ea580c",
        "MEDIUM": "#ca8a04",
        "LOW": "#16a34a",
    }
    return colors.get(severity.upper(), "#6b7280")
