"""Tests for inventory_match module."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from src.analyzer.inventory_match import match_vulnerability, _names_match


MOCK_INVENTORY = {
    "mcp_servers": [
        {
            "name": "@modelcontextprotocol/server-filesystem",
            "ecosystem": "npm",
            "tags": ["mcp-server"],
        },
        {
            "name": "mcp-server-fetch",
            "ecosystem": "npm",
            "tags": ["mcp-server"],
        },
    ],
    "npm_packages": [
        {
            "name": "langchain",
            "ecosystem": "npm",
            "tags": [],
        }
    ],
    "python_packages": [
        {
            "name": "anthropic",
            "ecosystem": "pypi",
            "tags": [],
        }
    ],
    "skills": [],
}


# ---------------------------------------------------------------------------
# _names_match unit tests
# ---------------------------------------------------------------------------

def test_exact_npm_package_match():
    assert _names_match("langchain", "langchain") is True


def test_scoped_npm_package_match():
    """@scope/pkg should match pkg (and vice versa)."""
    assert _names_match("@modelcontextprotocol/server-filesystem", "server-filesystem") is True


def test_no_match_for_unknown_package():
    assert _names_match("totally-unknown-pkg", "langchain") is False


def test_case_insensitive_match():
    assert _names_match("LangChain", "langchain") is True


# ---------------------------------------------------------------------------
# match_vulnerability — mocked inventory
# ---------------------------------------------------------------------------

def test_match_vulnerability_returns_components():
    """Exact name match should return the matching component name."""
    vuln = {
        "affected_component_name": "langchain",
        "affected_component_ecosystem": "npm",
        "title": "Vulnerability in langchain",
        "description": "A security issue in the langchain package.",
        "tags": [],
    }
    with patch("src.analyzer.inventory_match._load_inventory", return_value=MOCK_INVENTORY):
        matched = match_vulnerability(vuln)
    assert "langchain" in matched


def test_match_vulnerability_scoped_package():
    """Scoped npm package name should match the inventory entry."""
    vuln = {
        "affected_component_name": "@modelcontextprotocol/server-filesystem",
        "affected_component_ecosystem": "npm",
        "title": "Path traversal in MCP server",
        "description": "Path traversal in @modelcontextprotocol/server-filesystem.",
        "tags": [],
    }
    with patch("src.analyzer.inventory_match._load_inventory", return_value=MOCK_INVENTORY):
        matched = match_vulnerability(vuln)
    assert len(matched) > 0
    assert "@modelcontextprotocol/server-filesystem" in matched


def test_no_match_for_unknown_component():
    """A vulnerability for a package not in inventory should return empty list."""
    vuln = {
        "affected_component_name": "totally-unknown-pkg-xyz",
        "affected_component_ecosystem": "npm",
        "title": "Vulnerability in unknown-pkg",
        "description": "Some issue in a package we don't use.",
        "tags": [],
    }
    with patch("src.analyzer.inventory_match._load_inventory", return_value=MOCK_INVENTORY):
        matched = match_vulnerability(vuln)
    assert matched == []


def test_match_vulnerability_empty_inventory():
    """Empty inventory should always return empty list."""
    vuln = {
        "affected_component_name": "langchain",
        "affected_component_ecosystem": "npm",
        "title": "Vulnerability in langchain",
        "description": "A security issue.",
        "tags": [],
    }
    with patch("src.analyzer.inventory_match._load_inventory", return_value={}):
        matched = match_vulnerability(vuln)
    assert matched == []
