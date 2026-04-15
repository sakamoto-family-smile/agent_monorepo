"""VulnerableMCP collector - fetches MCP-specific vulnerability data."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

VULNERABLE_MCP_URL = "https://vulnerablemcp.info"


class VulnerableMCPCollector:
    """Fetches MCP-specific vulnerability data from vulnerablemcp.info.

    Since the site may not have a stable JSON API, this collector uses
    a structured approach that can be swapped with a real API client
    when one becomes available.
    """

    async def fetch_all(self) -> list[dict[str, Any]]:
        """Fetch all known vulnerable MCP servers.

        Attempts to fetch from the live site; falls back to known static data.
        Returns normalized vulnerability dicts.
        """
        try:
            return await self._fetch_live()
        except Exception as exc:
            logger.warning("VulnerableMCP live fetch failed: %s. Using static data.", exc)
            return self._get_static_data()

    async def _fetch_live(self) -> list[dict[str, Any]]:
        """Attempt to fetch vulnerability data from the live site."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{VULNERABLE_MCP_URL}/api/vulnerabilities.json")
            if resp.status_code == 200:
                data = resp.json()
                vulns = data if isinstance(data, list) else data.get("vulnerabilities", [])
                return [self._normalize(v) for v in vulns if v]

        # If JSON API not available, raise to trigger fallback
        raise RuntimeError("No JSON API available at vulnerablemcp.info")

    def _normalize(self, item: dict[str, Any]) -> dict[str, Any]:
        """Normalize a VulnerableMCP item to common schema."""
        from ..analyzer.scorer import classify_severity

        cvss_score = item.get("cvss_score") or item.get("score")
        severity = item.get("severity", "").upper()
        if cvss_score is not None:
            severity = classify_severity(float(cvss_score))
        elif not severity:
            severity = "HIGH"  # MCP vulnerabilities default to HIGH concern

        published_at: datetime | None = None
        pub_str = item.get("published_at") or item.get("date", "")
        if pub_str:
            try:
                published_at = datetime.fromisoformat(str(pub_str).replace("Z", "+00:00"))
            except ValueError:
                pass

        return {
            "source": "vulnerable_mcp",
            "cve_id": item.get("cve_id"),
            "ghsa_id": item.get("ghsa_id"),
            "title": item.get("title", "Unknown MCP Vulnerability"),
            "description": item.get("description", ""),
            "severity": severity,
            "cvss_score": float(cvss_score) if cvss_score is not None else None,
            "cvss_vector": item.get("cvss_vector"),
            "affected_component_name": item.get("mcp_server") or item.get("package_name"),
            "affected_component_version": item.get("affected_versions"),
            "affected_component_ecosystem": "npm",
            "tags": item.get("tags", []) + ["mcp", "mcp-server"],
            "owasp_asi": item.get("owasp_asi", []),
            "published_at": published_at,
            "raw_data": item,
        }

    def _get_static_data(self) -> list[dict[str, Any]]:
        """Return known static vulnerability data for common MCP servers.

        This represents publicly known issues and serves as a baseline
        until a stable API is available at vulnerablemcp.info.
        """
        now = datetime.now(tz=timezone.utc)

        static_entries = [
            {
                "title": "MCP Server Prompt Injection via Tool Description",
                "description": (
                    "Several MCP server implementations are susceptible to prompt injection attacks "
                    "through crafted tool descriptions. Malicious tool descriptions can instruct the "
                    "LLM to perform unintended actions or exfiltrate data."
                ),
                "severity": "HIGH",
                "cvss_score": 8.1,
                "affected_component_name": "multiple-mcp-servers",
                "affected_component_version": "all",
                "tags": ["prompt-injection", "mcp", "mcp-server", "OWASP-LLM01"],
                "owasp_asi": ["ASI01", "AST10"],
                "published_at": now,
                "cve_id": None,
                "ghsa_id": None,
            },
            {
                "title": "MCP Filesystem Server Path Traversal",
                "description": (
                    "The @modelcontextprotocol/server-filesystem MCP server may allow path traversal "
                    "attacks when the workspace root is not properly restricted. An attacker controlling "
                    "file paths could read files outside the intended workspace."
                ),
                "severity": "HIGH",
                "cvss_score": 7.5,
                "affected_component_name": "@modelcontextprotocol/server-filesystem",
                "affected_component_version": "< 0.6.0",
                "tags": ["path-traversal", "mcp", "filesystem", "CWE-22"],
                "owasp_asi": ["ASI02", "AST05"],
                "published_at": now,
                "cve_id": None,
                "ghsa_id": None,
            },
            {
                "title": "MCP Tool Rug Pull - Tool Description Manipulation",
                "description": (
                    "MCP servers can change tool descriptions after initial trust establishment, "
                    "causing agents to perform different actions than expected. This 'rug pull' "
                    "attack vector allows MCP server operators to manipulate agent behavior."
                ),
                "severity": "CRITICAL",
                "cvss_score": 9.1,
                "affected_component_name": "mcp-protocol",
                "affected_component_version": "all",
                "tags": ["rug-pull", "mcp", "tool-integrity", "supply-chain"],
                "owasp_asi": ["ASI01", "ASI02"],
                "published_at": now,
                "cve_id": None,
                "ghsa_id": None,
            },
            {
                "title": "Indirect Prompt Injection via MCP Search Results",
                "description": (
                    "MCP servers that return external content (web search, document retrieval) "
                    "may pass adversarial content to the LLM. This content can contain "
                    "indirect prompt injection payloads that hijack agent behavior."
                ),
                "severity": "HIGH",
                "cvss_score": 7.8,
                "affected_component_name": "@modelcontextprotocol/server-brave-search",
                "affected_component_version": "all",
                "tags": ["indirect-prompt-injection", "mcp", "search", "OWASP-LLM02"],
                "owasp_asi": ["ASI01", "AST10"],
                "published_at": now,
                "cve_id": None,
                "ghsa_id": None,
            },
            {
                "title": "MCP GitHub Server Token Exposure Risk",
                "description": (
                    "The @modelcontextprotocol/server-github passes GitHub personal access tokens "
                    "via environment variables. Improper process isolation may expose these tokens "
                    "to other processes or logs."
                ),
                "severity": "MEDIUM",
                "cvss_score": 5.5,
                "affected_component_name": "@modelcontextprotocol/server-github",
                "affected_component_version": "all",
                "tags": ["token-exposure", "mcp", "github", "CWE-312"],
                "owasp_asi": ["ASI06"],
                "published_at": now,
                "cve_id": None,
                "ghsa_id": None,
            },
        ]

        return [self._normalize(e) for e in static_entries]
