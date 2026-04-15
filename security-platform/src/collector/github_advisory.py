"""GitHub Advisory Database client."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

GITHUB_ADVISORY_URL = "https://api.github.com/advisories"


class GitHubAdvisoryCollector:
    """Fetches vulnerability advisories from the GitHub Advisory Database."""

    def __init__(self) -> None:
        self.token = settings.github_token
        headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self._headers = headers

    async def fetch_recent(
        self,
        ecosystems: list[str],
        days_back: int = 7,
    ) -> list[dict[str, Any]]:
        """Fetch recent advisories for the given ecosystems.

        Returns normalized vulnerability dicts.
        """
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days_back)
        all_vulns: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            for ecosystem in ecosystems:
                try:
                    vulns = await self._fetch_ecosystem(client, ecosystem, cutoff)
                    all_vulns.extend(vulns)
                except Exception as exc:
                    logger.warning("GitHub Advisory fetch failed for ecosystem '%s': %s", ecosystem, exc)

        # Deduplicate by GHSA ID
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for v in all_vulns:
            ghsa_id = v.get("ghsa_id", "")
            if ghsa_id and ghsa_id not in seen:
                seen.add(ghsa_id)
                unique.append(v)

        logger.info("GitHubAdvisoryCollector: fetched %d unique advisories", len(unique))
        return unique

    async def _fetch_ecosystem(
        self,
        client: httpx.AsyncClient,
        ecosystem: str,
        cutoff: datetime,
    ) -> list[dict[str, Any]]:
        """Fetch all advisories for a specific ecosystem published after cutoff."""
        items: list[dict[str, Any]] = []
        page = 1
        per_page = 100

        while True:
            params = {
                "ecosystem": ecosystem,
                "per_page": per_page,
                "page": page,
                "sort": "published",
                "direction": "desc",
            }

            try:
                resp = await client.get(GITHUB_ADVISORY_URL, params=params, headers=self._headers)
                resp.raise_for_status()
                advisories = resp.json()
            except httpx.HTTPStatusError as exc:
                logger.warning("GitHub Advisory HTTP error: %s", exc)
                break

            if not advisories:
                break

            for adv in advisories:
                published_str = adv.get("published_at", "")
                if published_str:
                    try:
                        pub_dt = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
                        if pub_dt < cutoff:
                            return items  # Sorted by date desc, so we can stop
                    except ValueError:
                        pass

                normalized = self._normalize(adv)
                if normalized:
                    items.append(normalized)

            if len(advisories) < per_page:
                break

            page += 1

        return items

    def _normalize(self, adv: dict[str, Any]) -> dict[str, Any] | None:
        """Normalize a GitHub Advisory item to common schema."""
        ghsa_id = adv.get("ghsa_id", "")
        if not ghsa_id:
            return None

        title = adv.get("summary", "No title")
        description = adv.get("description", "")

        # Extract CVSS
        cvss_score: float | None = None
        cvss_vector: str | None = None
        cvss = adv.get("cvss", {})
        if cvss:
            cvss_score = cvss.get("score")
            cvss_vector = cvss.get("vector_string")

        # Severity from GitHub
        gh_severity = adv.get("severity", "").upper()
        severity_map = {"CRITICAL": "CRITICAL", "HIGH": "HIGH", "MODERATE": "MEDIUM", "LOW": "LOW"}
        severity = severity_map.get(gh_severity, "LOW")
        if cvss_score is not None:
            from ..analyzer.scorer import classify_severity
            severity = classify_severity(cvss_score)

        # Affected packages
        affected_name: str | None = None
        affected_version: str | None = None
        affected_ecosystem: str | None = None
        vulnerabilities = adv.get("vulnerabilities", [])
        if vulnerabilities:
            first = vulnerabilities[0]
            pkg = first.get("package", {})
            affected_name = pkg.get("name")
            affected_ecosystem = pkg.get("ecosystem")
            patched = first.get("patched_versions", [])
            if patched:
                affected_version = f"< {patched[0]}"

        # CVE aliases
        cve_id: str | None = None
        for alias in adv.get("cve_id", []) if isinstance(adv.get("cve_id"), list) else []:
            if alias.startswith("CVE-"):
                cve_id = alias
                break
        if not cve_id and isinstance(adv.get("cve_id"), str):
            cve_id = adv["cve_id"] or None

        # Tags from CWE
        tags: list[str] = []
        for cwe in adv.get("cwes", []):
            cwe_id = cwe.get("cwe_id", "")
            if cwe_id:
                tags.append(cwe_id)

        published_at: datetime | None = None
        pub_str = adv.get("published_at", "")
        if pub_str:
            try:
                published_at = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        return {
            "source": "github_advisory",
            "cve_id": cve_id,
            "ghsa_id": ghsa_id,
            "title": title,
            "description": description,
            "severity": severity,
            "cvss_score": cvss_score,
            "cvss_vector": cvss_vector,
            "affected_component_name": affected_name,
            "affected_component_version": affected_version,
            "affected_component_ecosystem": affected_ecosystem,
            "tags": tags,
            "owasp_asi": [],
            "published_at": published_at,
            "raw_data": adv,
        }
