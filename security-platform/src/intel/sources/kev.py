"""CISA Known Exploited Vulnerabilities (全件 JSON 1 ファイル)。"""
from __future__ import annotations

import json
from typing import Any

import httpx

from ...common.http import with_retry
from ..signals import KevEntry


def fetch_kev(client: httpx.Client, url: str) -> bytes:
    def go() -> bytes:
        r = client.get(url)
        r.raise_for_status()
        return r.content

    return with_retry(go, what="cisa kev")


def parse_kev(body: bytes) -> list[KevEntry]:
    data: dict[str, Any] = json.loads(body)
    entries = []
    for v in data.get("vulnerabilities") or []:
        cve = (v.get("cveID") or "").strip()
        if not cve:
            continue
        entries.append(
            KevEntry(
                cve=cve,
                vendor=v.get("vendorProject"),
                product=v.get("product"),
                name=v.get("vulnerabilityName"),
                date_added=v.get("dateAdded"),
                due_date=v.get("dueDate"),
                ransomware=v.get("knownRansomwareCampaignUse"),
                short_description=v.get("shortDescription"),
            )
        )
    return entries
