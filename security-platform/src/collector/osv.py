"""OSV (Open Source Vulnerabilities) client."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

OSV_QUERY_URL = "https://api.osv.dev/v1/query"
OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_VULN_URL = "https://api.osv.dev/v1/vulns/{osv_id}"


class OSVCollector:
    """Fetches vulnerability data from the OSV API."""

    async def query_package(
        self,
        package_name: str,
        ecosystem: str,
    ) -> list[dict[str, Any]]:
        """Query OSV for vulnerabilities affecting a specific package.

        Returns normalized vulnerability dicts.
        """
        payload = {
            "package": {
                "name": package_name,
                "ecosystem": ecosystem,
            }
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(OSV_QUERY_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.warning("OSV query failed for %s/%s: %s", ecosystem, package_name, exc)
                return []

        vulns = data.get("vulns", [])
        return [self._normalize(v, package_name, ecosystem) for v in vulns if v]

    async def fetch_batch(
        self,
        packages: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        """Batch query OSV for a list of packages.

        Each package dict should have 'name' and 'ecosystem' keys.
        Returns normalized vulnerability dicts.
        """
        if not packages:
            return []

        queries = [
            {"package": {"name": p["name"], "ecosystem": p["ecosystem"]}}
            for p in packages
        ]

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                resp = await client.post(OSV_BATCH_URL, json={"queries": queries})
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.warning("OSV batch query failed: %s", exc)
                return []

        all_vulns: list[dict[str, Any]] = []
        results = data.get("results", [])

        for i, result in enumerate(results):
            pkg = packages[i] if i < len(packages) else {}
            for vuln in result.get("vulns", []):
                normalized = self._normalize(
                    vuln,
                    pkg.get("name", ""),
                    pkg.get("ecosystem", ""),
                )
                if normalized:
                    all_vulns.append(normalized)

        # Deduplicate by OSV ID
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for v in all_vulns:
            osv_id = v.get("cve_id") or v.get("ghsa_id") or v.get("title", "")
            if osv_id not in seen:
                seen.add(osv_id)
                unique.append(v)

        logger.info("OSVCollector: fetched %d unique vulnerabilities", len(unique))
        return unique

    def _normalize(
        self,
        vuln: dict[str, Any],
        package_name: str,
        ecosystem: str,
    ) -> dict[str, Any] | None:
        """Normalize an OSV vulnerability to common schema."""
        osv_id = vuln.get("id", "")
        if not osv_id:
            return None

        # Extract CVE / GHSA aliases
        cve_id: str | None = None
        ghsa_id: str | None = None
        for alias in vuln.get("aliases", []):
            if alias.startswith("CVE-") and not cve_id:
                cve_id = alias
            elif alias.startswith("GHSA-") and not ghsa_id:
                ghsa_id = alias

        summary = vuln.get("summary", "")
        details = vuln.get("details", "")
        title = summary or f"{osv_id}: {details[:120]}"

        # Extract affected version info
        affected_version: str | None = None
        affected_list = vuln.get("affected", [])
        if affected_list:
            first = affected_list[0]
            ranges = first.get("ranges", [])
            if ranges:
                for r in ranges:
                    for event in r.get("events", []):
                        if "fixed" in event:
                            affected_version = f"< {event['fixed']}"
                            break
                    if affected_version:
                        break

        # Extract CVSS score from severity
        cvss_score: float | None = None
        cvss_vector: str | None = None
        for sev in vuln.get("severity", []):
            if sev.get("type") == "CVSS_V3":
                cvss_vector = sev.get("score", "")
                # Parse CVSS vector to get base score if possible
                # For now just store the vector string
                break

        from ..analyzer.scorer import classify_severity
        severity = classify_severity(cvss_score)

        # Determine ecosystem from affected
        pkg_ecosystem = ecosystem
        if affected_list:
            first_affected = affected_list[0]
            pkg_info = first_affected.get("package", {})
            pkg_ecosystem = pkg_info.get("ecosystem", ecosystem)
            if not package_name:
                package_name = pkg_info.get("name", "")

        # Tags from database
        tags: list[str] = []
        database_specific = vuln.get("database_specific", {})
        cwe_ids = database_specific.get("cwe_ids", [])
        tags.extend(cwe_ids)

        published_at: datetime | None = None
        pub_str = vuln.get("published", "")
        if pub_str:
            try:
                published_at = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        return {
            "source": "osv",
            "cve_id": cve_id,
            "ghsa_id": ghsa_id,
            "title": title,
            "description": details or summary,
            "severity": severity,
            "cvss_score": cvss_score,
            "cvss_vector": cvss_vector,
            "affected_component_name": package_name or None,
            "affected_component_version": affected_version,
            "affected_component_ecosystem": pkg_ecosystem or None,
            "tags": tags,
            "owasp_asi": [],
            "published_at": published_at,
            "raw_data": vuln,
        }
