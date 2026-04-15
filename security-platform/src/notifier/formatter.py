"""Format vulnerability data for notifications."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..db.models import Vulnerability

SEVERITY_EMOJI = {
    "CRITICAL": "🚨",
    "HIGH": "🔴",
    "MEDIUM": "🟡",
    "LOW": "🟢",
}


def format_immediate(vuln: "Vulnerability") -> str:
    """Format a single vulnerability for immediate alert notifications.

    Example output:
    🚨 [CRITICAL] CVE-2024-1234: MCP Server RCE Vulnerability
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    Source: nvd
    CVSS Score: 9.8 (CRITICAL)
    Affected: @modelcontextprotocol/server-filesystem < 0.6.0
    Inventory Match: YES - agent-system-1
    OWASP ASI: ASI02, AST05

    Description:
    Path traversal vulnerability in MCP filesystem server...

    Recommended Actions:
    - Update to patched version
    - Restrict workspace root
    """
    emoji = SEVERITY_EMOJI.get(vuln.severity, "⚪")
    ids = " / ".join(filter(None, [vuln.cve_id, vuln.ghsa_id])) or "N/A"
    cvss = f"{vuln.cvss_score:.1f}" if vuln.cvss_score else "N/A"
    affected = vuln.affected_component_name or "unknown"
    if vuln.affected_component_version:
        affected += f" {vuln.affected_component_version}"

    matched_str = ""
    if vuln.inventory_match and vuln.matched_components:
        matched_str = f"Inventory Match: YES - {', '.join(vuln.matched_components)}\n"
    else:
        matched_str = "Inventory Match: No\n"

    owasp_str = ""
    if vuln.owasp_asi:
        owasp_str = f"OWASP ASI: {', '.join(vuln.owasp_asi)}\n"

    description = (vuln.description or "")[:400]
    if len(vuln.description or "") > 400:
        description += "..."

    recommended = ""
    if vuln.recommended_actions:
        recommended = f"\nRecommended Actions:\n{vuln.recommended_actions}\n"

    lines = [
        f"{emoji} [{vuln.severity}] {ids}: {vuln.title[:80]}",
        "━" * 48,
        f"Source: {vuln.source}",
        f"CVSS Score: {cvss} ({vuln.severity})",
        f"Affected: {affected}",
        matched_str.rstrip(),
    ]
    if owasp_str:
        lines.append(owasp_str.rstrip())
    lines.extend([
        "",
        "Description:",
        description,
    ])
    if recommended:
        lines.append(recommended)

    return "\n".join(lines)


def format_digest(vulns: list["Vulnerability"]) -> str:
    """Format multiple vulnerabilities for a daily/weekly digest.

    Groups by severity, shows summary table.
    """
    if not vulns:
        return "No new vulnerabilities in this period."

    # Group by severity
    by_severity: dict[str, list["Vulnerability"]] = {
        "CRITICAL": [],
        "HIGH": [],
        "MEDIUM": [],
        "LOW": [],
    }
    for v in vulns:
        by_severity.get(v.severity, by_severity["LOW"]).append(v)

    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"Security Digest - {now}",
        "=" * 48,
        "",
        "Summary:",
        f"  CRITICAL: {len(by_severity['CRITICAL'])}",
        f"  HIGH:     {len(by_severity['HIGH'])}",
        f"  MEDIUM:   {len(by_severity['MEDIUM'])}",
        f"  LOW:      {len(by_severity['LOW'])}",
        f"  TOTAL:    {len(vulns)}",
        "",
    ]

    for severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        sev_vulns = by_severity[severity]
        if not sev_vulns:
            continue
        emoji = SEVERITY_EMOJI.get(severity, "")
        lines.append(f"{emoji} {severity} ({len(sev_vulns)})")
        lines.append("-" * 32)
        for v in sev_vulns[:10]:  # Cap at 10 per severity
            ids = v.cve_id or v.ghsa_id or "N/A"
            affected = v.affected_component_name or "unknown"
            match_flag = " [!INVENTORY]" if v.inventory_match else ""
            lines.append(f"  • {ids}: {v.title[:60]}{match_flag}")
            lines.append(f"    Affected: {affected} | CVSS: {v.cvss_score or 'N/A'}")
        if len(sev_vulns) > 10:
            lines.append(f"  ... and {len(sev_vulns) - 10} more")
        lines.append("")

    return "\n".join(lines)
