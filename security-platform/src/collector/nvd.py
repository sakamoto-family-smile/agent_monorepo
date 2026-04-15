"""NVD CVE API 2.0 client for fetching vulnerability data."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

NVD_BASE_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
# NVD rate limits: 5 req/30s without key, 50 req/30s with key
DEFAULT_SLEEP_SECONDS = 6.0
KEYED_SLEEP_SECONDS = 0.6


class NVDCollector:
    """Fetches CVE data from the NVD API 2.0."""

    def __init__(self) -> None:
        self.api_key = settings.nvd_api_key
        self.sleep_seconds = KEYED_SLEEP_SECONDS if self.api_key else DEFAULT_SLEEP_SECONDS
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.api_key:
            headers["apiKey"] = self.api_key
        self._headers = headers

    async def fetch_recent(
        self,
        keywords: list[str],
        days_back: int = 7,
    ) -> list[dict[str, Any]]:
        """Fetch CVEs modified in the last `days_back` days matching any keyword.

        Returns a list of normalized vulnerability dicts.
        """
        end_dt = datetime.now(tz=timezone.utc)
        start_dt = end_dt - timedelta(days=days_back)
        start_str = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000")
        end_str = end_dt.strftime("%Y-%m-%dT%H:%M:%S.000")

        all_vulns: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            for keyword in keywords:
                try:
                    vulns = await self._fetch_keyword(client, keyword, start_str, end_str)
                    all_vulns.extend(vulns)
                    await asyncio.sleep(self.sleep_seconds)
                except Exception as exc:
                    logger.warning("NVD fetch failed for keyword '%s': %s", keyword, exc)

        # Deduplicate by CVE ID
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for v in all_vulns:
            cve_id = v.get("cve_id", "")
            if cve_id and cve_id not in seen:
                seen.add(cve_id)
                unique.append(v)

        logger.info("NVDCollector: fetched %d unique CVEs", len(unique))
        return unique

    async def _fetch_keyword(
        self,
        client: httpx.AsyncClient,
        keyword: str,
        start_str: str,
        end_str: str,
    ) -> list[dict[str, Any]]:
        """Fetch a single page (up to 2000 results) for a keyword."""
        params: dict[str, str | int] = {
            "keywordSearch": keyword,
            "keywordExactMatch": "",
            "lastModStartDate": start_str,
            "lastModEndDate": end_str,
            "resultsPerPage": 100,
            "startIndex": 0,
        }

        all_items: list[dict[str, Any]] = []
        total_results = 1  # Will be updated after first response

        while params["startIndex"] < total_results:
            resp = await client.get(NVD_BASE_URL, params=params, headers=self._headers)
            resp.raise_for_status()
            data = resp.json()
            total_results = data.get("totalResults", 0)
            vulnerabilities = data.get("vulnerabilities", [])

            for item in vulnerabilities:
                normalized = self._normalize(item)
                if normalized:
                    all_items.append(normalized)

            params["startIndex"] = int(params["startIndex"]) + len(vulnerabilities)
            if len(vulnerabilities) == 0:
                break
            if params["startIndex"] < total_results:
                await asyncio.sleep(self.sleep_seconds)

        return all_items

    def _normalize(self, item: dict[str, Any]) -> dict[str, Any] | None:
        """Normalize a raw NVD vulnerability item to common schema."""
        cve = item.get("cve", {})
        cve_id = cve.get("id", "")
        if not cve_id:
            return None

        descriptions = cve.get("descriptions", [])
        description = next(
            (d["value"] for d in descriptions if d.get("lang") == "en"),
            descriptions[0]["value"] if descriptions else "",
        )

        # Extract CVSS score
        cvss_score: float | None = None
        cvss_vector: str | None = None
        metrics = cve.get("metrics", {})
        for metric_key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
            if metric_key in metrics and metrics[metric_key]:
                m = metrics[metric_key][0]
                cvss_data = m.get("cvssData", {})
                cvss_score = cvss_data.get("baseScore")
                cvss_vector = cvss_data.get("vectorString")
                break

        # Extract affected packages
        affected_name: str | None = None
        affected_version: str | None = None
        affected_ecosystem: str | None = None
        configurations = cve.get("configurations", [])
        if configurations:
            for config in configurations:
                for node in config.get("nodes", []):
                    for cpe_match in node.get("cpeMatch", []):
                        criteria = cpe_match.get("criteria", "")
                        if criteria:
                            parts = criteria.split(":")
                            if len(parts) >= 5:
                                affected_name = parts[4] if parts[4] != "*" else None
                                affected_version = parts[5] if len(parts) > 5 and parts[5] != "*" else None
                            break
                    if affected_name:
                        break
                if affected_name:
                    break

        # Extract tags from weaknesses
        tags: list[str] = []
        weaknesses = cve.get("weaknesses", [])
        for weakness in weaknesses:
            for wd in weakness.get("description", []):
                val = wd.get("value", "")
                if val and val != "NVD-CWE-noinfo":
                    tags.append(val)

        published_at: datetime | None = None
        pub_str = cve.get("published", "")
        if pub_str:
            try:
                published_at = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        from ..analyzer.scorer import classify_severity

        severity = classify_severity(cvss_score) if cvss_score is not None else "LOW"

        return {
            "source": "nvd",
            "cve_id": cve_id,
            "ghsa_id": None,
            "title": f"{cve_id}: {description[:120]}",
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
            "raw_data": item,
        }
