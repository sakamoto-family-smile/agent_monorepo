"""Tests for NVDCollector."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

import pytest
from src.collector.nvd import NVDCollector


# ---------------------------------------------------------------------------
# Sample NVD API response items for testing _normalize
# ---------------------------------------------------------------------------

SAMPLE_CRITICAL_ITEM = {
    "cve": {
        "id": "CVE-2024-9999",
        "published": "2024-01-15T12:00:00.000",
        "descriptions": [
            {"lang": "en", "value": "A critical RCE vulnerability in the MCP server allows remote code execution."}
        ],
        "metrics": {
            "cvssMetricV31": [
                {
                    "cvssData": {
                        "baseScore": 9.8,
                        "vectorString": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
                    }
                }
            ]
        },
        "configurations": [
            {
                "nodes": [
                    {
                        "cpeMatch": [
                            {
                                "criteria": "cpe:2.3:a:example:mcp_server:1.0.0:*:*:*:*:*:*:*",
                                "vulnerable": True,
                            }
                        ]
                    }
                ]
            }
        ],
        "weaknesses": [
            {
                "description": [{"value": "CWE-78"}]
            }
        ],
    }
}

SAMPLE_NO_CVSS_ITEM = {
    "cve": {
        "id": "CVE-2024-8888",
        "published": "2024-02-01T00:00:00.000",
        "descriptions": [
            {"lang": "en", "value": "A vulnerability with no CVSS score yet."}
        ],
        "metrics": {},
        "configurations": [],
        "weaknesses": [],
    }
}

SAMPLE_MCP_TAGGED_ITEM = {
    "cve": {
        "id": "CVE-2024-7777",
        "published": "2024-03-01T00:00:00.000",
        "descriptions": [
            {
                "lang": "en",
                "value": "A model context protocol server allows prompt injection attacks.",
            }
        ],
        "metrics": {
            "cvssMetricV31": [
                {
                    "cvssData": {
                        "baseScore": 7.5,
                        "vectorString": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
                    }
                }
            ]
        },
        "configurations": [],
        "weaknesses": [],
    }
}


# ---------------------------------------------------------------------------
# Unit tests for _normalize (no network calls)
# ---------------------------------------------------------------------------

def test_normalize_cve_critical():
    collector = NVDCollector()
    result = collector._normalize(SAMPLE_CRITICAL_ITEM)
    assert result is not None
    assert result["cve_id"] == "CVE-2024-9999"
    assert result["cvss_score"] == 9.8
    assert result["severity"] == "CRITICAL"
    assert result["source"] == "nvd"
    assert "CWE-78" in result["tags"]


def test_normalize_cve_no_cvss():
    collector = NVDCollector()
    result = collector._normalize(SAMPLE_NO_CVSS_ITEM)
    assert result is not None
    assert result["cve_id"] == "CVE-2024-8888"
    assert result["cvss_score"] is None
    assert result["severity"] == "LOW"  # no CVSS → default LOW


def test_normalize_cve_mcp_tagged():
    """'model context protocol' in description → tags should not fail."""
    collector = NVDCollector()
    result = collector._normalize(SAMPLE_MCP_TAGGED_ITEM)
    assert result is not None
    assert result["cve_id"] == "CVE-2024-7777"
    assert result["cvss_score"] == 7.5
    assert result["severity"] == "HIGH"


def test_keyword_filter_matches():
    """When description contains a matching keyword, normalize should return a result."""
    collector = NVDCollector()
    item = {
        "cve": {
            "id": "CVE-2024-1111",
            "published": "2024-01-01T00:00:00.000",
            "descriptions": [{"lang": "en", "value": "MCP tool injection vulnerability."}],
            "metrics": {},
            "configurations": [],
            "weaknesses": [],
        }
    }
    result = collector._normalize(item)
    assert result is not None
    assert result["cve_id"] == "CVE-2024-1111"


def test_keyword_filter_no_match():
    """An item with no CVE id should return None."""
    collector = NVDCollector()
    bad_item = {"cve": {"id": "", "descriptions": [], "metrics": {}, "configurations": [], "weaknesses": []}}
    result = collector._normalize(bad_item)
    assert result is None


# ---------------------------------------------------------------------------
# Mock HTTP: test that fetch_recent calls the NVD API
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_fetch_recent_calls_nvd_api():
    """fetch_recent should call the NVD API URL and return normalized results."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "totalResults": 1,
        "vulnerabilities": [SAMPLE_CRITICAL_ITEM],
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("src.collector.nvd.httpx.AsyncClient", return_value=mock_client):
        with patch("src.collector.nvd.asyncio.sleep", new_callable=AsyncMock):
            collector = NVDCollector()
            results = await collector.fetch_recent(keywords=["mcp"], days_back=7)

    assert len(results) == 1
    assert results[0]["cve_id"] == "CVE-2024-9999"
    # Verify the API was called
    mock_client.get.assert_called()
    call_kwargs = mock_client.get.call_args
    assert "nvd.nist.gov" in call_kwargs[0][0] or "nvd.nist.gov" in str(call_kwargs)
